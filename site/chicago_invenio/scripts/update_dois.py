#!/usr/bin/env python3
"""Synchronize DOIs between InvenioRDM and DataCite with rate limiting."""

from __future__ import annotations

import argparse
import csv
import datetime
import logging
import random
import os
import time
import requests
from typing import Optional, Tuple
from urllib.parse import quote

from datacite.errors import DataCiteError, DataCiteNotFoundError
from flask import current_app, has_app_context
from idutils.normalizers import normalize_doi
from idutils.validators import is_doi
from invenio_access.permissions import system_identity
from invenio_db import db
from invenio_pidstore.errors import PIDDoesNotExistError
from invenio_rdm_records.proxies import current_rdm_records_service
from invenio_rdm_records.records.api import RDMRecord
from chicago_invenio.config.datacite_providers import RestrictedDataCitePIDProvider as DataCitePIDProvider
from invenio_rdm_records.utils import ChainObject

logger = logging.getLogger(__name__)


def _ensure_boolean(value):
    """Convert string boolean values to actual booleans.

    Kubernetes/environment variables often pass booleans as strings.
    This converts 'true'/'false' (case-insensitive) to bool.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


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


def _doi_exists_in_datacite(
    provider: DataCitePIDProvider,
    doi: str,
    *,
    debug_lookups: bool = False,
) -> bool:
    api_url = getattr(provider.client.api, "api_url", "<unknown>")
    if debug_lookups:
        logger.info("[doi-check] lookup DOI=%s via %s", doi, api_url)

    try:
        datacite_url = provider.client.api.get_doi(doi)
        if debug_lookups:
            logger.info(
                "[doi-check] found DOI=%s resolved_url=%s",
                doi,
                datacite_url,
            )
        return True
    except DataCiteNotFoundError as e:
        if debug_lookups:
            logger.warning(
                "[doi-check] NOT FOUND DOI=%s via %s (%s)",
                doi,
                api_url,
                str(e),
            )
        return False


def _probe_doi(provider: DataCitePIDProvider, doi: str) -> None:
    api_url = getattr(provider.client.api, "api_url", "<unknown>")
    normalized = normalize_doi(doi) if is_doi(doi) else doi
    encoded = quote(normalized, safe="")

    logger.info(
        "[doi-probe] input=%s normalized=%s api_url=%s",
        doi,
        normalized,
        api_url,
    )

    try:
        datacite_url = provider.client.api.get_doi(normalized)
        logger.info(
            "[doi-probe] authenticated DataCite lookup FOUND normalized=%s url=%s",
            normalized,
            datacite_url,
        )
    except DataCiteError as e:
        logger.warning(
            "[doi-probe] authenticated DataCite lookup FAILED normalized=%s error_type=%s error=%s",
            normalized,
            type(e).__name__,
            str(e),
        )

    public_api_url = f"https://api.datacite.org/dois/{encoded}"
    try:
        resp = requests.get(public_api_url, timeout=15)
        body_excerpt = resp.text[:300].replace("\n", " ")
        logger.info(
            "[doi-probe] public DataCite lookup status=%s url=%s body_excerpt=%s",
            resp.status_code,
            public_api_url,
            body_excerpt,
        )
    except Exception as e:
        logger.warning(
            "[doi-probe] public DataCite lookup FAILED url=%s error=%s",
            public_api_url,
            str(e),
        )

    doi_org_url = f"https://doi.org/{encoded}"
    try:
        resp = requests.get(doi_org_url, allow_redirects=False, timeout=15)
        logger.info(
            "[doi-probe] doi.org status=%s location=%s url=%s",
            resp.status_code,
            resp.headers.get("Location"),
            doi_org_url,
        )
    except Exception as e:
        logger.warning(
            "[doi-probe] doi.org check FAILED url=%s error=%s",
            doi_org_url,
            str(e),
        )


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
    debug_datacite_lookups: bool = False,
    probe_dois: Optional[list[str]] = None,
) -> dict:
    if not has_app_context():
        raise RuntimeError("No Flask application context found.")
    if not current_app.config.get("DATACITE_ENABLED", False):
        raise RuntimeError("DATACITE_ENABLED is False.")

    provider = DataCitePIDProvider("datacite")

    # Workaround: ensure DATACITE_TEST_MODE is a boolean, not a string
    # (Kubernetes/environment may pass it as string "false" or "true")
    config_test_mode = current_app.config.get("DATACITE_TEST_MODE", False)
    if isinstance(config_test_mode, str):
        logger.warning(
            "DATACITE_TEST_MODE is a string (%r), converting to boolean. "
            "Recommend fixing config loading in invenio app. See chicago_invenio/config.py or invenio.cfg",
            config_test_mode,
        )
        config_test_mode = _ensure_boolean(config_test_mode)
        # Force the provider to use the corrected boolean value
        provider.client._config_overrides["DATACITE_TEST_MODE"] = config_test_mode
        # Clear the cached API client so it gets recreated with the corrected boolean
        provider.client._api = None

    # Diagnostic: check for DATACITE_TEST_MODE config vs actual provider state
    actual_api_url = getattr(provider.client.api, "api_url", "")
    is_test_api = "test.datacite.org" in actual_api_url
    config_test_mode_bool = _ensure_boolean(config_test_mode)

    if config_test_mode_bool != is_test_api:
        logger.warning(
            "DATACITE_TEST_MODE config mismatch: config=%s actual_api_url=%s (is_test=%s)",
            config_test_mode_bool,
            actual_api_url,
            is_test_api,
        )

        # Check for env var overrides
        env_test_mode = os.environ.get("INVENIO_DATACITE_TEST_MODE")
        env_prefix = os.environ.get("INVENIO_DATACITE_PREFIX")
        if env_test_mode or env_prefix:
            logger.warning(
                "Potential env var overrides: INVENIO_DATACITE_TEST_MODE=%s INVENIO_DATACITE_PREFIX=%s",
                env_test_mode,
                env_prefix,
            )

    if debug_datacite_lookups:
        logger.info(
            "DataCite client context: api_url=%s username=%s prefix=%s",
            getattr(provider.client.api, "api_url", "<unknown>"),
            getattr(provider.client.api, "username", "<unknown>"),
            getattr(provider.client.api, "prefix", "<unknown>"),
        )

    if probe_dois:
        for probe_doi in probe_dois:
            _probe_doi(provider, probe_doi)

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

    start_time = datetime.datetime.now()
    logger.info("Starting DOI sync at %s", start_time.isoformat())

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
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            logger.info(
                "Progress (elapsed=%.1fs): scanned=%s reg=%s upd=%s par_reg=%s par_upd=%s err=%s",
                elapsed,
                stats["scanned"],
                stats["registered"],
                stats["updated"],
                stats["parents_registered"],
                stats["parents_updated"],
                stats["errors"],
            )

        try:
            record = RDMRecord.get_record(record_id)
            enriched = current_rdm_records_service.read(system_identity, record["id"]).to_dict()
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
                    debug_lookups=debug_datacite_lookups,
                )
                if dry_run:
                    action = "update" if exists_remotely else "register"
                    logger.info(
                        "[dry-run] %s record DOI %s -> %s", action, doi, record_url
                    )
                    doi_operations.append((doi, record_url, "record", action))
                else:
                    if exists_remotely:
                        if doi_pid is not None:
                            ok = provider.update(doi_pid, record=enriched, url=record_url)
                        else:
                            doc = provider.serializer.dump_obj(enriched)
                            doc["event"] = "publish"
                            provider.client.api.update_doi(
                                doi=doi,
                                metadata=doc,
                                url=record_url,
                            )
                            ok = True
                        if ok:
                            stats["updated"] += 1
                            doi_operations.append((doi, record_url, "record", "update"))
                    else:
                        if debug_datacite_lookups and doi_pid is not None:
                            logger.warning(
                                "[doi-check] local PID exists but remote lookup returned not found; DOI=%s",
                                doi,
                            )
                        if doi_pid is not None:
                            ok = provider.register(doi_pid, record=enriched, url=record_url)
                        else:
                            doc = provider.serializer.dump_obj(enriched)
                            provider.client.api.public_doi(
                                metadata=doc,
                                url=record_url,
                                doi=doi,
                            )
                            ok = True
                        if ok:
                            stats["registered"] += 1
                            doi_operations.append((doi, record_url, "record", "register"))

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
                debug_lookups=debug_datacite_lookups,
            )
            if dry_run:
                action = "update" if parent_exists_remotely else "register"
                logger.info(
                    "[dry-run] %s parent DOI %s -> %s",
                    action,
                    parent_doi,
                    parent_url,
                )
                doi_operations.append((parent_doi, parent_url, "parent", action))
            else:
                if parent_exists_remotely:
                    if parent_doi_pid is not None:
                        ok = provider.update(
                            parent_doi_pid,
                            record=enriched,
                            url=parent_url,
                        )
                    else:
                        doc = provider.serializer.dump_obj(enriched)
                        doc["event"] = "publish"
                        provider.client.api.update_doi(
                            doi=parent_doi,
                            metadata=doc,
                            url=parent_url,
                        )
                        ok = True
                    if ok:
                        stats["parents_updated"] += 1
                        doi_operations.append((parent_doi, parent_url, "parent", "update"))
                else:
                    if debug_datacite_lookups and parent_doi_pid is not None:
                        logger.warning(
                            "[doi-check] local parent PID exists but remote lookup returned not found; DOI=%s",
                            parent_doi,
                        )
                    if parent_doi_pid is not None:
                        ok = provider.register(
                            parent_doi_pid,
                            record=enriched,
                            url=parent_url,
                        )
                    else:
                        doc = provider.serializer.dump_obj(enriched)
                        provider.client.api.public_doi(
                            metadata=doc,
                            url=parent_url,
                            doi=parent_doi,
                        )
                        ok = True
                    if ok:
                        stats["parents_registered"] += 1
                        doi_operations.append((parent_doi, parent_url, "parent", "register"))
            if not dry_run:
                db.session.commit()
        except (DataCiteError, PIDDoesNotExistError, Exception):
            db.session.rollback()
            stats["errors"] += 1
            logger.exception("Failed DOI sync for DB record %s", record_id)

    end_time = datetime.datetime.now()
    elapsed_seconds = (end_time - start_time).total_seconds()
    elapsed_str = str(datetime.timedelta(seconds=int(elapsed_seconds)))

    logger.info(
        "Done (started=%s ended=%s elapsed=%s): scanned=%s without_doi=%s skip_prefix=%s reg=%s upd=%s par_without=%s "
        "par_skip_prefix=%s par_reg=%s par_upd=%s errors=%s",
        start_time.isoformat(),
        end_time.isoformat(),
        elapsed_str,
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
                writer.writerow(["DOI", "URL", "Type", "Action"])
                for doi, url, doi_type, action in doi_operations:
                    writer.writerow([doi, url, doi_type, action])
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
    parser.add_argument(
        "--debug-datacite-lookups",
        action="store_true",
        help="Log detailed DataCite DOI lookup behavior.",
    )
    parser.add_argument(
        "--probe-doi",
        action="append",
        default=[],
        help=(
            "Probe a DOI before sync using authenticated DataCite lookup, public "
            "DataCite API, and doi.org. Repeat flag to probe multiple DOIs."
        ),
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
        debug_datacite_lookups=args.debug_datacite_lookups,
        probe_dois=args.probe_doi,
    )


if __name__ == "__main__":
    main()
