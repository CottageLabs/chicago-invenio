#!/usr/bin/env python3
"""Synchronize DOIs between InvenioRDM and DataCite with rate limiting."""

from __future__ import annotations

import argparse
import csv
import logging
import random
import time
from typing import Optional, Tuple
from urllib.parse import quote

from datacite.errors import DataCiteError, DataCiteNotFoundError
from flask import current_app, has_app_context
from idutils.normalizers import normalize_doi
from idutils.validators import is_doi
from invenio_db import db
from invenio_pidstore.errors import PIDDoesNotExistError
from invenio_rdm_records.records.api import RDMRecord
from invenio_rdm_records.services.pids.providers.datacite import DataCitePIDProvider
from invenio_rdm_records.utils import ChainObject

logger = logging.getLogger(__name__)


class RateLimiter:
    """Manages request throttling and exponential backoff."""

    def __init__(self, throttle_seconds: float = 0.5, max_retries: int = 3):
        self.throttle_seconds = throttle_seconds
        self.max_retries = max_retries
        self.last_request_time = 0.0
        self.backoff_multiplier = 2.0
        self.backoff_jitter = 0.1

    def wait_if_needed(self) -> None:
        elapsed = time.time() - self.last_request_time
        if elapsed < self.throttle_seconds:
            time.sleep(self.throttle_seconds - elapsed)

    def mark_request(self) -> None:
        self.last_request_time = time.time()

    def get_backoff_delay(self, attempt: int) -> float:
        base_delay = self.throttle_seconds * (self.backoff_multiplier ** attempt)
        jitter = base_delay * self.backoff_jitter * random.random()
        return base_delay + jitter

    def retry_with_backoff(self, func, *args, **kwargs):
        last_exception = None
        for attempt in range(self.max_retries):
            try:
                self.wait_if_needed()
                result = func(*args, **kwargs)
                self.mark_request()
                return result
            except DataCiteNotFoundError:
                self.mark_request()
                raise
            except DataCiteError as e:
                self.mark_request()
                last_exception = e
                if attempt < self.max_retries - 1:
                    delay = self.get_backoff_delay(attempt)
                    logger.warning(
                        "DataCite error (attempt %d/%d), retrying in %.1fs: %s",
                        attempt + 1, self.max_retries, delay, str(e))
                    time.sleep(delay)
                else:
                    logger.error("DataCite request failed after %d attempts", self.max_retries)
                    raise
        if last_exception:
            raise last_exception


def _extract_record_doi(
    record: RDMRecord, provider: DataCitePIDProvider
) -> Tuple[Optional[str], Optional[object]]:
    record_pid = getattr(record, "pid", None)
    if record_pid and record_pid.pid_value and is_doi(record_pid.pid_value):
        return normalize_doi(record_pid.pid_value), record_pid
    doi_entry = (record.get("pids") or {}).get("doi") or {}
    doi_value = doi_entry.get("identifier")
    if doi_value and is_doi(doi_value):
        doi_value = normalize_doi(doi_value)
        provider_name = doi_entry.get("provider")
        try:
            return doi_value, provider.get(doi_value, pid_provider=provider_name)
        except PIDDoesNotExistError:
            return doi_value, None
    return None, None


def _extract_parent_doi(
    record: RDMRecord, provider: DataCitePIDProvider
) -> Tuple[Optional[str], Optional[object]]:
    parent_doi_entry = (record.parent.get("pids") or {}).get("doi") or {}
    parent_doi = parent_doi_entry.get("identifier")
    if not parent_doi or not is_doi(parent_doi):
        return None, None
    parent_doi = normalize_doi(parent_doi)
    parent_provider_name = parent_doi_entry.get("provider")
    try:
        return parent_doi, provider.get(parent_doi, pid_provider=parent_provider_name)
    except PIDDoesNotExistError:
        return parent_doi, None


def _parent_pid_payload_and_landing_record(record: RDMRecord):
    latest_record = record
    if not latest_record.versions.is_latest:
        latest = RDMRecord.get_latest_published_by_parent(latest_record.parent)
        latest_record = latest or latest_record
    payload = ChainObject(
        latest_record.parent,
        latest_record,
        aliases={"_parent": latest_record.parent, "_child": latest_record},
    )
    return payload, latest_record


def _record_landing_url(
    record: RDMRecord, doi: str, url_template: Optional[str] = None
) -> str:
    site_ui_url = (current_app.config.get("SITE_UI_URL") or "").rstrip("/")
    record_identifier = record.get("id") or doi
    record_identifier = quote(str(record_identifier), safe="")
    if url_template:
        return url_template.format(
            site_ui_url=site_ui_url,
            record_id=record_identifier,
            doi=doi,
        )
    return f"{site_ui_url}/records/{record_identifier}"


def _doi_exists_in_datacite(provider: DataCitePIDProvider, doi: str) -> bool:
    try:
        provider.client.api.get_doi(doi)
        return True
    except DataCiteNotFoundError:
        return False


def _iter_record_ids(batch_size: int):
    if batch_size <= 0:
        raise ValueError(f"batch_size must be > 0, got {batch_size}")

    last_id = None
    while True:
        query = RDMRecord.model_cls.query.with_entities(RDMRecord.model_cls.id)
        if last_id is not None:
            query = query.filter(RDMRecord.model_cls.id > last_id)
        query = query.order_by(RDMRecord.model_cls.id).limit(batch_size)
        rows = query.all()
        if not rows:
            break
        for row in rows:
            yield row[0]

        next_last_id = rows[-1][0]
        if last_id is not None and next_last_id <= last_id:
            logger.error(
                "Record-id iterator cursor did not advance: last_id=%s next_last_id=%s batch_size=%s",
                last_id,
                next_last_id,
                batch_size,
            )
            raise RuntimeError("Record-id iterator cursor did not advance.")

        last_id = next_last_id


def sync_all_dois(
    *,
    batch_size: int = 100,
    limit: Optional[int] = None,
    dry_run: bool = False,
    url_template: Optional[str] = None,
    progress_every: Optional[int] = None,
    output_csv: Optional[str] = None,
    throttle_seconds: float = 0.5,
    max_retries: int = 3,
) -> dict:
    if not has_app_context():
        raise RuntimeError("No Flask application context found.")
    if not current_app.config.get("DATACITE_ENABLED", False):
        raise RuntimeError("DATACITE_ENABLED is False.")

    provider = DataCitePIDProvider("datacite")
    stats = {
        "scanned": 0,
        "without_doi": 0,
        "skipped_prefix_mismatch": 0,
        "registered": 0,
        "updated": 0,
        "parents_without_doi": 0,
        "parents_skipped_prefix_mismatch": 0,
        "parents_registered": 0,
        "parents_updated": 0,
        "errors": 0,
    }
    rate_limiter = RateLimiter(throttle_seconds=throttle_seconds, max_retries=max_retries)
    logger.info(
        "Initialized rate limiter: throttle=%.1fs, max_retries=%d",
        throttle_seconds,
        max_retries,
    )

    doi_operations = []
    datacite_prefix = (current_app.config.get("DATACITE_PREFIX") or "").strip()
    if not datacite_prefix:
        raise RuntimeError("DATACITE_PREFIX is empty.")
    managed_prefix = f"{datacite_prefix}/"

    processed_parent_ids = set()
    for record_id in _iter_record_ids(batch_size):
        if limit is not None and stats["scanned"] >= limit:
            break
        stats["scanned"] += 1
        if progress_every and stats["scanned"] % progress_every == 0:
            logger.info(
                "Progress: scanned=%s reg=%s upd=%s par_reg=%s par_upd=%s err=%s",
                stats["scanned"],
                stats["registered"],
                stats["updated"],
                stats["parents_registered"],
                stats["parents_updated"],
                stats["errors"],
            )

        try:
            record = RDMRecord.get_record(record_id)
            doi, doi_pid = _extract_record_doi(record, provider)
            if not doi:
                stats["without_doi"] += 1
                continue
            if not doi.startswith(managed_prefix):
                stats["skipped_prefix_mismatch"] += 1
            else:
                record_url = _record_landing_url(record, doi, url_template=url_template)
                exists_remotely = rate_limiter.retry_with_backoff(
                    _doi_exists_in_datacite,
                    provider,
                    doi,
                )
                if dry_run:
                    action = "update" if exists_remotely else "register"
                    logger.info(
                        "[dry-run] %s record DOI %s -> %s", action, doi, record_url
                    )
                    doi_operations.append((doi, record_url, "record"))
                else:
                    if exists_remotely:
                        if doi_pid is not None:
                            ok = provider.update(doi_pid, record=record, url=record_url)
                        else:
                            doc = provider.serializer.dump_obj(record)
                            doc["event"] = "publish"
                            provider.client.api.update_doi(
                                doi=doi,
                                metadata=doc,
                                url=record_url,
                            )
                            ok = True
                        if ok:
                            stats["updated"] += 1
                            doi_operations.append((doi, record_url, "record"))
                    else:
                        if doi_pid is not None:
                            ok = provider.register(doi_pid, record=record, url=record_url)
                        else:
                            doc = provider.serializer.dump_obj(record)
                            provider.client.api.public_doi(
                                metadata=doc,
                                url=record_url,
                                doi=doi,
                            )
                            ok = True
                        if ok:
                            stats["registered"] += 1
                            doi_operations.append((doi, record_url, "record"))

            parent_id = getattr(record.parent, "id", None)
            if parent_id is not None and parent_id in processed_parent_ids:
                continue
            if parent_id is not None:
                processed_parent_ids.add(parent_id)
            parent_doi, parent_doi_pid = _extract_parent_doi(record, provider)
            if not parent_doi:
                stats["parents_without_doi"] += 1
                continue
            if not parent_doi.startswith(managed_prefix):
                stats["parents_skipped_prefix_mismatch"] += 1
                continue
            parent_record_payload, parent_landing_record = (
                _parent_pid_payload_and_landing_record(record)
            )
            parent_url = _record_landing_url(
                parent_landing_record,
                parent_doi,
                url_template=url_template,
            )
            parent_exists_remotely = rate_limiter.retry_with_backoff(
                _doi_exists_in_datacite,
                provider,
                parent_doi,
            )
            if dry_run:
                action = "update" if parent_exists_remotely else "register"
                logger.info(
                    "[dry-run] %s parent DOI %s -> %s",
                    action,
                    parent_doi,
                    parent_url,
                )
                doi_operations.append((parent_doi, parent_url, "parent"))
            else:
                if parent_exists_remotely:
                    if parent_doi_pid is not None:
                        ok = provider.update(
                            parent_doi_pid,
                            record=parent_record_payload,
                            url=parent_url,
                        )
                    else:
                        doc = provider.serializer.dump_obj(parent_record_payload)
                        doc["event"] = "publish"
                        provider.client.api.update_doi(
                            doi=parent_doi,
                            metadata=doc,
                            url=parent_url,
                        )
                        ok = True
                    if ok:
                        stats["parents_updated"] += 1
                        doi_operations.append((parent_doi, parent_url, "parent"))
                else:
                    if parent_doi_pid is not None:
                        ok = provider.register(
                            parent_doi_pid,
                            record=parent_record_payload,
                            url=parent_url,
                        )
                    else:
                        doc = provider.serializer.dump_obj(parent_record_payload)
                        provider.client.api.public_doi(
                            metadata=doc,
                            url=parent_url,
                            doi=parent_doi,
                        )
                        ok = True
                    if ok:
                        stats["parents_registered"] += 1
                        doi_operations.append((parent_doi, parent_url, "parent"))
            if not dry_run:
                db.session.commit()
        except (DataCiteError, PIDDoesNotExistError, Exception):
            db.session.rollback()
            stats["errors"] += 1
            logger.exception("Failed DOI sync for DB record %s", record_id)

    logger.info(
        "Done: scanned=%s without_doi=%s skip_prefix=%s reg=%s upd=%s par_without=%s "
        "par_skip_prefix=%s par_reg=%s par_upd=%s errors=%s",
        stats["scanned"],
        stats["without_doi"],
        stats["skipped_prefix_mismatch"],
        stats["registered"],
        stats["updated"],
        stats["parents_without_doi"],
        stats["parents_skipped_prefix_mismatch"],
        stats["parents_registered"],
        stats["parents_updated"],
        stats["errors"],
    )

    if output_csv and doi_operations:
        try:
            with open(output_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["DOI", "URL", "Type"])
                for doi, url, doi_type in doi_operations:
                    writer.writerow([doi, url, doi_type])
            logger.info("Wrote %d DOI operations to %s", len(doi_operations), output_csv)
        except Exception as e:
            logger.error("Failed to write CSV output: %s", e)

    return stats


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync record DOIs with DataCite")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--progress-every",
        type=int,
        default=None,
        help="Log progress every N records scanned.",
    )
    parser.add_argument(
        "--output-csv",
        default=None,
        help="Path to write CSV of DOI operations.",
    )
    parser.add_argument("--url-template", default=None, help="Optional URL template.")
    parser.add_argument(
        "--throttle-seconds",
        type=float,
        default=0.5,
        help="Minimum seconds between DataCite requests (default: 0.5).",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Maximum retry attempts on DataCite errors (default: 3).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sync_all_dois(
        batch_size=args.batch_size,
        limit=args.limit,
        dry_run=args.dry_run,
        progress_every=args.progress_every,
        output_csv=args.output_csv,
        url_template=args.url_template,
        throttle_seconds=args.throttle_seconds,
        max_retries=args.max_retries,
    )


if __name__ == "__main__":
    main()
