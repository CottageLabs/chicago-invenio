"""Delete a single file from an already-published record, without a new version.

InvenioRDM deliberately locks file deletion on published records to the
internal `system_identity` (`can_delete_files = [SystemProcess()]` in
invenio_rdm_records/services/permissions.py) - there is no UI, admin panel,
or REST API path for this, even for superusers. The supported route is
always: edit -> new version -> remove file from the draft -> publish. This
script is for the rare case where that isn't acceptable (e.g. a takedown of
an accidentally uploaded file where a new version isn't wanted) and the
system-level route is genuinely intended.

Because it bypasses the draft/versioning workflow, there is no automatic
audit trail of why the file disappeared, and the record is not reindexed by
the underlying file service call - both are handled explicitly below. This
also does not touch a registered DOI's metadata; check DOI implications
separately if the file was part of a DOI's registered content.

Usage:
    pipenv run invenio shell site/chicago_invenio/scripts/delete_file_from_record.py \\
        -- -- <record_id> <file_key> [options]

    The double `--` is required whenever any option (--yes, --reason) is
    passed: `invenio shell` runs this via IPython, and both Click (invenio
    shell's own option parser) and IPython (which re-parses its argv looking
    for its own flags) each consume one `--` as their "stop parsing options"
    marker before the rest reaches this script's argparse. With only
    positional args (no options) this isn't needed, e.g. a dry run can be:
        pipenv run invenio shell site/chicago_invenio/scripts/delete_file_from_record.py \\
            <record_id> <file_key>

    By default this is a dry run: it resolves the record and file, prints
    what would be deleted, and makes no changes. Pass --yes to actually
    delete.

Options:
    --yes            Actually perform the deletion (default: dry run only).
    --reason TEXT     Why this file is being removed. Strongly recommended -
                      logged since Invenio keeps no record of this otherwise.
"""

import argparse
import logging
import sys
from datetime import datetime, timezone

from invenio_access.permissions import system_identity
from invenio_db import db
from invenio_pidstore.errors import PIDDoesNotExistError
from invenio_rdm_records.proxies import current_rdm_records_service as records_service
from invenio_rdm_records.records.api import RDMRecord

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def delete_file(record_id: str, file_key: str, *, confirm: bool, reason: str | None) -> None:
    try:
        record = RDMRecord.pid.resolve(record_id, registered_only=False)
    except PIDDoesNotExistError:
        logger.error("No published record found for id %s", record_id)
        sys.exit(1)

    if file_key not in record.files:
        logger.error(
            "Record %s has no file with key %r. Available keys: %s",
            record_id,
            file_key,
            ", ".join(sorted(record.files.keys())) or "(none)",
        )
        sys.exit(1)

    file_record = record.files[file_key]
    file_obj = file_record.file
    logger.info(
        "Target file: record=%s key=%r size=%s checksum=%s mimetype=%s",
        record_id,
        file_key,
        getattr(file_obj, "size", "?"),
        getattr(file_obj, "checksum", "?"),
        getattr(file_record, "mimetype", "?"),
    )

    if not confirm:
        logger.info("Dry run only, no changes made. Re-run with --yes to delete.")
        return

    logger.info(
        "Deleting file (record=%s key=%r reason=%s requested_at=%s) ...",
        record_id,
        file_key,
        reason or "(none given)",
        datetime.now(timezone.utc).isoformat(),
    )

    # Publishing locks a record's file bucket at the storage layer
    # (invenio_files_rest.models.ObjectVersion.create checks bucket.locked
    # directly) - this is separate from and unaffected by the
    # can_delete_files permission bypass above, so it must be unlocked here
    # too or FileService.delete_file raises BucketLockedError.
    bucket_was_locked = record.files.bucket.locked
    if bucket_was_locked:
        logger.info("Bucket is locked (published record) - unlocking for this operation.")
        record.files.unlock()
        db.session.commit()

    try:
        records_service.files.delete_file(system_identity, record_id, file_key)
    finally:
        if bucket_was_locked:
            relocked_record = RDMRecord.pid.resolve(record_id, registered_only=False)
            relocked_record.files.lock()
            db.session.commit()
            logger.info("Bucket re-locked.")

    # The file service's own commit doesn't pass an indexer, so the search
    # index won't reflect the change unless we do this explicitly.
    updated_record = RDMRecord.pid.resolve(record_id, registered_only=False)
    records_service.indexer.index(updated_record)

    logger.info(
        "Deleted and reindexed. record=%s key=%r checksum=%s reason=%s",
        record_id,
        file_key,
        getattr(file_obj, "checksum", "?"),
        reason or "(none given)",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delete a single file from a published record without a new version."
    )
    parser.add_argument("record_id", help="Record PID (e.g. abcd1-23456).")
    parser.add_argument("file_key", help="File key/filename to delete.")
    parser.add_argument(
        "--yes",
        dest="confirm",
        action="store_true",
        help="Actually perform the deletion (default: dry run only).",
    )
    parser.add_argument(
        "--reason",
        default=None,
        help="Why this file is being removed, for the log line (recommended).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    delete_file(args.record_id, args.file_key, confirm=args.confirm, reason=args.reason)


if __name__ == "__main__":
    main()
