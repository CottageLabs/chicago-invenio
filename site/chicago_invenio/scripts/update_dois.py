#!/usr/bin/env python3
"""Synchronize managed DOIs between InvenioRDM and DataCite.

The script iterates over all published `RDMRecord` rows, extracts a DOI PID,
checks if that DOI exists in DataCite, and then:

- registers DOI + metadata + landing page URL if missing in DataCite
- updates DOI URL/metadata if already present in DataCite

Usage (recommended in app context):
	invenio shell site/chicago_invenio/scripts/update_dois.py --batch-size 200

Or from an Invenio shell:
	from chicago_invenio.scripts.update_dois import sync_all_dois
	sync_all_dois()
"""

from __future__ import annotations

import argparse
import logging
from typing import Optional, Tuple
from urllib.parse import quote

from idutils.normalizers import normalize_doi
from idutils.validators import is_doi
from datacite.errors import DataCiteError, DataCiteNotFoundError
from flask import current_app, has_app_context
from invenio_db import db
from invenio_pidstore.errors import PIDDoesNotExistError
from invenio_rdm_records.records.api import RDMRecord
from invenio_rdm_records.services.pids.providers.datacite import DataCitePIDProvider
from invenio_rdm_records.utils import ChainObject

logger = logging.getLogger(__name__)


def _extract_record_doi(
	record: RDMRecord, provider: DataCitePIDProvider
) -> Tuple[Optional[str], Optional[object]]:
	"""Extract DOI value and local DOI PID object from a record.

	Priority:
	  1) `record.pid` if it is a DOI.
	  2) `record["pids"]["doi"]["identifier"]`.
	"""
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
	"""Extract DOI value and local DOI PID object from a parent record."""
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
	"""Build parent metadata payload plus the record used for landing URL generation."""
	latest_record = record
	if not latest_record.versions.is_latest:
		latest = RDMRecord.get_latest_published_by_parent(latest_record.parent)
		latest_record = latest or latest_record

	return ChainObject(
		latest_record.parent,
		latest_record,
		aliases={
			"_parent": latest_record.parent,
			"_child": latest_record,
		},
	), latest_record


def _record_landing_url(record: RDMRecord, doi: str, url_template: Optional[str] = None) -> str:
	"""Build the target landing page URL for DataCite."""
	site_ui_url = (current_app.config.get("SITE_UI_URL") or "").rstrip("/")

	# We prefer the record's local id (usually the recid) for `/records/<id>` links.
	# If unavailable, we fall back to the DOI.
	record_identifier = record.get("id") or doi
	record_identifier = quote(str(record_identifier), safe="")

	if url_template:
		return url_template.format(site_ui_url=site_ui_url, record_id=record_identifier, doi=doi)

	return f"{site_ui_url}/records/{record_identifier}"


def _doi_exists_in_datacite(provider: DataCitePIDProvider, doi: str) -> bool:
	"""Return True if DOI exists in DataCite, False if not found."""
	try:
		provider.client.api.get_doi(doi)
		return True
	except DataCiteNotFoundError:
		return False


def sync_all_dois(
	*,
	batch_size: int = 100,
	limit: Optional[int] = None,
	dry_run: bool = False,
	url_template: Optional[str] = None,
) -> dict:
	"""Synchronize all managed record DOIs with DataCite.

	Args:
		batch_size: SQLAlchemy yield batch size.
		limit: Optional cap on number of records processed.
		dry_run: If True, do not call DataCite or write DB state.
		url_template: Optional URL template with placeholders:
			`{site_ui_url}`, `{record_id}`, `{doi}`.

	Returns:
		A dictionary of run statistics.
	"""
	if not has_app_context():
		raise RuntimeError(
			"No Flask application context found. "
			"Run this script via `invenio shell ...` or call inside `app.app_context()`."
		)

	if not current_app.config.get("DATACITE_ENABLED", False):
		raise RuntimeError("DATACITE_ENABLED is False; DataCite synchronization is disabled.")

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

	datacite_prefix = (current_app.config.get("DATACITE_PREFIX") or "").strip()
	if not datacite_prefix:
		raise RuntimeError("DATACITE_PREFIX is empty; cannot safely scope managed DOI updates.")

	managed_prefix = f"{datacite_prefix}/"
	processed_parent_ids = set()

	query = (
		RDMRecord.model_cls.query.order_by(RDMRecord.model_cls.id).yield_per(batch_size)
	)

	for model in query:
		if limit is not None and stats["scanned"] >= limit:
			break

		stats["scanned"] += 1

		try:
			record = RDMRecord.get_record(model.id)
			doi, doi_pid = _extract_record_doi(record, provider)

			if not doi:
				stats["without_doi"] += 1
				continue

			if not doi.startswith(managed_prefix):
				stats["skipped_prefix_mismatch"] += 1
			else:
				record_url = _record_landing_url(record, doi, url_template=url_template)
				exists_remotely = _doi_exists_in_datacite(provider, doi)

				if dry_run:
					action = "update" if exists_remotely else "register"
					logger.info("[dry-run] %s record DOI %s -> %s", action, doi, record_url)
				else:
					if exists_remotely:
						if doi_pid is not None:
							ok = provider.update(doi_pid, record=record, url=record_url)
						else:
							doc = provider.serializer.dump_obj(record)
							doc["event"] = "publish"
							provider.client.api.update_doi(doi=doi, metadata=doc, url=record_url)
							ok = True

						if ok:
							stats["updated"] += 1
					else:
						if doi_pid is not None:
							ok = provider.register(doi_pid, record=record, url=record_url)
						else:
							doc = provider.serializer.dump_obj(record)
							provider.client.api.public_doi(metadata=doc, url=record_url, doi=doi)
							ok = True

						if ok:
							stats["registered"] += 1

			parent_id = getattr(record.parent, "id", None)
			if parent_id is not None and parent_id in processed_parent_ids:
				db.session.commit()
				continue

			if parent_id is not None:
				processed_parent_ids.add(parent_id)
			parent_doi, parent_doi_pid = _extract_parent_doi(record, provider)

			if not parent_doi:
				stats["parents_without_doi"] += 1
				db.session.commit()
				continue

			if not parent_doi.startswith(managed_prefix):
				stats["parents_skipped_prefix_mismatch"] += 1
				db.session.commit()
				continue

			parent_record_payload, parent_landing_record = _parent_pid_payload_and_landing_record(record)
			parent_url = _record_landing_url(parent_landing_record, parent_doi, url_template=url_template)
			parent_exists_remotely = _doi_exists_in_datacite(provider, parent_doi)

			if dry_run:
				action = "update" if parent_exists_remotely else "register"
				logger.info("[dry-run] %s parent DOI %s -> %s", action, parent_doi, parent_url)
			else:
				if parent_exists_remotely:
					if parent_doi_pid is not None:
						ok = provider.update(parent_doi_pid, record=parent_record_payload, url=parent_url)
					else:
						doc = provider.serializer.dump_obj(parent_record_payload)
						doc["event"] = "publish"
						provider.client.api.update_doi(doi=parent_doi, metadata=doc, url=parent_url)
						ok = True

					if ok:
						stats["parents_updated"] += 1
				else:
					if parent_doi_pid is not None:
						ok = provider.register(parent_doi_pid, record=parent_record_payload, url=parent_url)
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

			db.session.commit()

		except (DataCiteError, PIDDoesNotExistError, Exception):
			db.session.rollback()
			stats["errors"] += 1
			logger.exception("Failed DOI sync for DB record %s", model.id)

	logger.info(
		"Done: scanned=%s without_doi=%s skipped_prefix_mismatch=%s registered=%s updated=%s parents_without_doi=%s parents_skipped_prefix_mismatch=%s parents_registered=%s parents_updated=%s errors=%s",
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

	return stats


def _parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Sync record DOIs with DataCite")
	parser.add_argument("--batch-size", type=int, default=100)
	parser.add_argument("--limit", type=int, default=None)
	parser.add_argument("--dry-run", action="store_true")
	parser.add_argument(
		"--url-template",
		default=None,
		help="Optional template, e.g. '{site_ui_url}/records/{record_id}'.",
	)
	return parser.parse_args()


def main() -> None:
	args = _parse_args()
	logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
	sync_all_dois(
		batch_size=args.batch_size,
		limit=args.limit,
		dry_run=args.dry_run,
		url_template=args.url_template,
	)


if __name__ == "__main__":
	main()




