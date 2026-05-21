"""Script to migrate file download statistics from legacy TIND system to InvenioRDM.

This script reads download statistics from CSV files exported from the legacy system
and inserts them as file-download events into InvenioRDM's OpenSearch statistics indices.

Data Sources:
    - file_download_statistics.csv: Download events with id_bibrec, id_bibdoc, download_time
    - file_information.csv: File metadata mapping id_bibdocfile to file_key (UUID)

Usage:
    pipenv run invenio shell site/chicago_invenio/scripts/migrate_statistics.py [options]

Options:
    --stats-csv PATH     Path to file_download_statistics.csv (default: same directory)
    --files-csv PATH     Path to file_information.csv (default: same directory)
    --batch-size N       Number of events per bulk insert (default: 1000)
    --limit N            Only process first N download records (for testing)
    --dry-run            Don't actually insert, just validate and count
"""

import csv
import hashlib
import logging
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional, Tuple

import click
from dateutil import parser as date_parser
from invenio_access.permissions import system_identity
from invenio_rdm_records.proxies import current_rdm_records_service
from invenio_search import current_search_client
from invenio_search.utils import prefix_index
from opensearchpy.helpers import bulk

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

file_cache = {}

class StatisticsMigrator:
    """Migrates legacy download statistics to InvenioRDM OpenSearch."""

    def __init__(
        self,
        stats_csv_path: str,
        files_csv_path: str,
        files_folder: str,
        batch_size: int = 1000,
        dry_run: bool = False
    ):
        """Initialize the migrator.

        Args:
            stats_csv_path: Path to file_download_statistics.csv
            files_csv_path: Path to file_information.csv
            batch_size: Number of events to bulk insert at once
            dry_run: If True, don't actually insert documents
        """
        self.stats_csv_path = stats_csv_path
        self.files_csv_path = files_csv_path
        self.files_folder = files_folder
        self.batch_size = batch_size
        self.dry_run = dry_run

        # Cache for tind_id -> record mapping
        self._record_cache: Dict[int, Optional[Dict[str, Any]]] = {}

        # Cache for file information: (id_bibrec, id_bibdocfile) -> file_info
        self._file_info_cache: Dict[Tuple[int, int], Dict[str, Any]] = {}

        # Statistics
        self.stats = {
            'downloads_processed': 0,
            'downloads_skipped_no_file': 0,
            'downloads_skipped_no_record': 0,
            'events_inserted': 0,
            'unique_records': set(),
            'errors': 0,
        }

    def load_file_information(self) -> None:
        """Load file_information.csv into memory cache."""
        logger.info(f"Loading file information from {self.files_csv_path}")

        with open(self.files_csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    id_bibrec = int(row['id_bibrec'])
                    id_bibdocfile = int(row['id_bibdocfile'])
                    key = (id_bibrec, id_bibdocfile)

                    self._file_info_cache[key] = {
                        'file_id': row['file_id'],
                        'file_key': row['file_key'],  # UUID
                        'docname': row['docname'],
                        'format': row.get('format', ''),
                        'version': row.get('version', '1'),
                        'creation_date': row.get('creation_date'),
                    }
                except (KeyError, ValueError) as e:
                    logger.warning(f"Error parsing file info row: {e}")

        logger.info(f"Loaded {len(self._file_info_cache)} file information records")

    def get_record_by_tind_id(self, tind_id: int) -> Optional[Dict[str, Any]]:
        """Look up InvenioRDM record by chicago:tind_id custom field.

        Args:
            tind_id: The legacy TIND record ID

        Returns:
            Record dict with id, parent_id, and bucket_id, or None if not found
        """
        if tind_id in self._record_cache:
            return self._record_cache[tind_id]

        try:
            # Search by custom field - escape the colon in field name
            results = current_rdm_records_service.search(
                identity=system_identity,
                q=f'custom_fields.chicago\\:tind_id:{tind_id}',
                size=1
            )

            hits = list(results.hits)
            if hits:
                record = hits[0]
                record_data = {
                    'recid': record['id'],
                    'parent_recid': record.get('parent', {}).get('id'),
                    'bucket_id': record.get('files', {}).get('bucket_id'),
                    'tind_id': tind_id,
                }
                self._record_cache[tind_id] = record_data
                self.stats['unique_records'].add(tind_id)
                return record_data
            else:
                self._record_cache[tind_id] = None
                return None

        except Exception as e:
            logger.warning(f"Error looking up record for tind_id={tind_id}: {e}")
            self._record_cache[tind_id] = None
            return None

    def get_file_info(self, id_bibrec: int, id_bibdoc: int) -> Optional[Dict[str, Any]]:
        """Get file information from cache.

        Args:
            id_bibrec: TIND record ID
            id_bibdoc: TIND document ID (maps to id_bibdocfile)

        Returns:
            File info dict or None if not found
        """
        key = (id_bibrec, id_bibdoc)
        return self._file_info_cache.get(key)

    def generate_unique_ids(self, timestamp: datetime, bucket_id: str, file_id: str) -> Tuple[str, str]:
        """Generate visitor_id and unique_session_id for legacy events.

        For legacy events we don't have user info, so we generate deterministic
        IDs based on the event timestamp and file info.

        Args:
            timestamp: Event timestamp
            bucket_id: Record's bucket ID
            file_id: File's UUID

        Returns:
            Tuple of (visitor_id, unique_session_id)
        """
        # Use timestamp as salt for deterministic hashing
        day_str = timestamp.strftime('%Y%m%d')
        hour_str = timestamp.strftime('%Y%m%d%H')

        # Create base string from file info and timestamp
        base = f"legacy:{bucket_id}:{file_id}:{day_str}"

        # Generate visitor_id (per day)
        visitor_id = hashlib.sha224(base.encode('utf-8')).hexdigest()

        # Generate unique_session_id (per hour)
        session_base = f"legacy:{bucket_id}:{file_id}:{hour_str}"
        unique_session_id = hashlib.sha224(session_base.encode('utf-8')).hexdigest()

        return visitor_id, unique_session_id

    def get_file_size(self, tind_id: str, filename:str) -> int:

        if not self.files_folder:
            return 0

        file_path = os.path.join(self.files_folder, tind_id, filename)

        if file_path in file_cache:
            return file_cache[file_path]

        if os.path.exists(file_path):
            file_cache[file_path] = os.path.getsize(file_path)
            return file_cache[file_path]

        file_cache[file_path] = 0

        return 0


    def build_event_document(
        self,
        download_time: str,
        file_info: Dict[str, Any],
        record_info: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Build a file-download event document for OpenSearch.

        Args:
            download_time: Timestamp string from CSV
            file_info: File information dict
            record_info: InvenioRDM record info dict

        Returns:
            Event document dict ready for indexing, or None if invalid
        """
        try:
            # Parse timestamp
            timestamp = date_parser.parse(download_time)
            # Truncate to seconds as per invenio-stats
            timestamp = timestamp.replace(microsecond=0)
            timestamp_str = timestamp.strftime('%Y-%m-%dT%H:%M:%S')

            bucket_id = record_info.get('bucket_id') or ''
            file_id = file_info['file_key']  # UUID

            # Generate unique IDs for legacy event
            visitor_id, unique_session_id = self.generate_unique_ids(
                timestamp, bucket_id, file_id
            )

            # Build unique_id as bucket_id_file_id (same as invenio-stats)
            unique_id = f"{bucket_id}_{file_id}"

            # Construct filename from docname + format
            docname = file_info.get('docname', '')
            file_format = file_info.get('format', '')
            if file_format and not docname.endswith(file_format):
                file_key = f"{docname}{file_format}"
            else:
                file_key = docname

            event = {
                'timestamp': timestamp_str,
                'bucket_id': bucket_id,
                'file_id': file_id,
                'file_key': file_key,
                'size': self.get_file_size(str(record_info['tind_id']), file_key),
                'recid': record_info['recid'],
                'parent_recid': record_info.get('parent_recid', ''),
                'via_api': False,  # Legacy downloads were via UI
                'unique_id': unique_id,
                'visitor_id': visitor_id,
                'unique_session_id': unique_session_id,
                'is_robot': False,  # Assume human for legacy
                'is_machine': False,
                'country': None,
                'updated_timestamp': datetime.utcnow().isoformat(),
            }

            return event

        except Exception as e:
            logger.warning(f"Error building event document: {e}")
            return None

    def generate_event_id(self, timestamp_str: str, unique_id: str, visitor_id: str) -> str:
        """Generate a unique document ID for the event.

        This follows the same pattern as invenio-stats to enable deduplication.

        Args:
            timestamp_str: ISO format timestamp
            unique_id: The event's unique_id field
            visitor_id: The event's visitor_id field

        Returns:
            Document ID string
        """
        hash_input = unique_id.encode('utf-8') + str(visitor_id).encode('utf-8')
        return f"{timestamp_str}-{hashlib.sha1(hash_input).hexdigest()}"

    def get_index_name(self, timestamp: datetime) -> str:
        """Get the OpenSearch index name for a given timestamp.

        Index pattern: {prefix}events-stats-file-download-{YYYY-MM}

        Args:
            timestamp: Event timestamp

        Returns:
            Full index name
        """
        suffix = timestamp.strftime('%Y-%m')
        base_index = prefix_index('events-stats-file-download')
        return f"{base_index}-{suffix}"

    def iterate_downloads(self, limit: Optional[int] = None) -> Iterator[Dict[str, str]]:
        """Iterate over download records from CSV.

        Args:
            limit: Optional limit on number of records to process

        Yields:
            Download record dicts from CSV
        """
        with open(self.stats_csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                if limit and i >= limit:
                    break
                yield row

    def generate_bulk_actions(
        self,
        limit: Optional[int] = None
    ) -> Iterator[Dict[str, Any]]:
        """Generate bulk index actions for all download events.

        Args:
            limit: Optional limit on downloads to process

        Yields:
            OpenSearch bulk action dicts
        """
        for row in self.iterate_downloads(limit):
            self.stats['downloads_processed'] += 1

            try:
                id_bibrec = int(row['id_bibrec'])
                id_bibdoc = int(row['id_bibdoc'])
                download_time = row['download_time']
            except (KeyError, ValueError) as e:
                logger.warning(f"Error parsing download row: {e}")
                self.stats['errors'] += 1
                continue

            # Get file information
            file_info = self.get_file_info(id_bibrec, id_bibdoc)
            if not file_info:
                self.stats['downloads_skipped_no_file'] += 1
                continue

            # Get InvenioRDM record
            record_info = self.get_record_by_tind_id(id_bibrec)
            if not record_info:
                self.stats['downloads_skipped_no_record'] += 1
                continue

            # Build event document
            event = self.build_event_document(download_time, file_info, record_info)
            if not event:
                self.stats['errors'] += 1
                continue

            # Parse timestamp for index name
            timestamp = date_parser.parse(download_time)
            index_name = self.get_index_name(timestamp)

            # Generate document ID
            doc_id = self.generate_event_id(
                event['timestamp'],
                event['unique_id'],
                event['visitor_id']
            )

            yield {
                '_id': doc_id,
                '_index': index_name,
                '_op_type': 'index',
                '_source': event,
            }

            # Log progress periodically
            if self.stats['downloads_processed'] % 10000 == 0:
                logger.info(f"Processed {self.stats['downloads_processed']} downloads...")

    def run(self, limit: Optional[int] = None) -> Dict[str, Any]:
        """Run the migration.

        Args:
            limit: Optional limit on downloads to process (for testing)

        Returns:
            Statistics dict with counts
        """
        logger.info("Starting statistics migration")
        start_time = time.time()

        # Load file information into memory
        self.load_file_information()

        if self.dry_run:
            logger.info("DRY RUN - no documents will be inserted")
            # Just count events that would be generated
            for action in self.generate_bulk_actions(limit):
                self.stats['events_inserted'] += 1
        else:
            # Perform bulk indexing
            actions = []
            for action in self.generate_bulk_actions(limit):
                actions.append(action)

                if len(actions) >= self.batch_size:
                    success, errors = self._bulk_insert(actions)
                    self.stats['events_inserted'] += success
                    self.stats['errors'] += len(errors) if errors else 0
                    actions = []

            # Insert remaining actions
            if actions:
                success, errors = self._bulk_insert(actions)
                self.stats['events_inserted'] += success
                self.stats['errors'] += len(errors) if errors else 0

        elapsed = time.time() - start_time

        # Convert set to count for serialization
        self.stats['unique_records'] = len(self.stats['unique_records'])

        logger.info(f"Migration completed in {elapsed:.2f} seconds")
        logger.info(f"Statistics: {self.stats}")

        return self.stats

    def _bulk_insert(self, actions: List[Dict[str, Any]]) -> Tuple[int, List]:
        """Perform bulk insert to OpenSearch.

        Args:
            actions: List of bulk action dicts

        Returns:
            Tuple of (success_count, errors_list)
        """
        try:
            success, errors = bulk(
                current_search_client,
                actions,
                stats_only=False,
                raise_on_error=False,
                chunk_size=self.batch_size
            )
            if errors:
                for error in errors[:5]:  # Log first 5 errors
                    logger.error(f"Bulk insert error: {error}")
            return success, errors
        except Exception as e:
            logger.error(f"Bulk insert failed: {e}")
            return 0, [str(e)]


@click.command()
@click.option(
    '--stats-csv',
    default=None,
    help='Path to file_download_statistics.csv'
)
@click.option(
    '--files-csv',
    default=None,
    help='Path to file_information.csv'
)
@click.option(
    '--files-folder',
    default=None,
    help='Path to file root folder'
)
@click.option(
    '--batch-size',
    default=1000,
    type=int,
    help='Number of events per bulk insert'
)
@click.option(
    '--limit',
    default=None,
    type=int,
    help='Only process first N download records (for testing)'
)
@click.option(
    '--dry-run',
    is_flag=True,
    default=False,
    help="Don't actually insert, just validate and count"
)
def main(stats_csv, files_csv, files_folder, batch_size, limit, dry_run):
    """Migrate legacy file download statistics to InvenioRDM."""
    # Default paths are relative to this script's directory
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if stats_csv is None:
        stats_csv = os.path.join(script_dir, 'file_download_statistics.csv')
    if files_csv is None:
        files_csv = os.path.join(script_dir, 'file_information.csv')

    # Validate files exist
    if not os.path.exists(stats_csv):
        logger.error(f"Statistics CSV not found: {stats_csv}")
        sys.exit(1)
    if not os.path.exists(files_csv):
        logger.error(f"Files CSV not found: {files_csv}")
        sys.exit(1)

    logger.info(f"Statistics CSV: {stats_csv}")
    logger.info(f"Files CSV: {files_csv}")
    logger.info(f"Batch size: {batch_size}")
    if limit:
        logger.info(f"Limit: {limit} records")
    if dry_run:
        logger.info("Mode: DRY RUN")

    migrator = StatisticsMigrator(
        stats_csv_path=stats_csv,
        files_csv_path=files_csv,
        files_folder=files_folder,
        batch_size=batch_size,
        dry_run=dry_run
    )

    stats = migrator.run(limit=limit)

    # Print summary
    print("\n" + "=" * 60)
    print("MIGRATION SUMMARY")
    print("=" * 60)
    print(f"Downloads processed:      {stats['downloads_processed']:,}")
    print(f"Events inserted:          {stats['events_inserted']:,}")
    print(f"Skipped (no file info):   {stats['downloads_skipped_no_file']:,}")
    print(f"Skipped (no record):      {stats['downloads_skipped_no_record']:,}")
    print(f"Unique records:           {stats['unique_records']:,}")
    print(f"Errors:                   {stats['errors']:,}")
    print("=" * 60)


if __name__ == '__main__':
    main()
