"""Custom DataCite serializer that emits only mandatory metadata fields."""

from __future__ import annotations

from datetime import datetime

from flask import current_app, has_app_context
from invenio_rdm_records.resources.serializers import DataCite43JSONSerializer


class ChicagoSafeDataCite43JSONSerializer(DataCite43JSONSerializer):
    """Serialize DataCite JSON using only mandatory fields.

    This avoids DataCite rejections caused by optional metadata that may not
    conform exactly to DataCite's controlled vocabularies.
    """

    @staticmethod
    def _creator_name(creator):
        person_or_org = creator.get("person_or_org") or {}
        name = (person_or_org.get("name") or creator.get("name") or "").strip()
        if name:
            return name

        given = (
            person_or_org.get("given_name")
            or creator.get("givenName")
            or creator.get("given_name")
            or ""
        ).strip()
        family = (
            person_or_org.get("family_name")
            or creator.get("familyName")
            or creator.get("family_name")
            or ""
        ).strip()
        return f"{family}, {given}".strip(", ")

    @staticmethod
    def _publication_year(metadata):
        publication_date = str(metadata.get("publication_date") or "").strip()
        if len(publication_date) >= 4 and publication_date[:4].isdigit():
            return publication_date[:4]
        return str(datetime.utcnow().year)

    def dump_obj(self, obj):
        metadata = obj.get("metadata") or {}
        pids = obj.get("pids") or {}

        doi = (
            pids.get("doi", {}).get("identifier")
            or getattr(getattr(obj, "pid", None), "pid_value", None)
        )

        creators = []
        for creator in metadata.get("creators") or []:
            name = self._creator_name(creator)
            if name:
                creators.append({"name": name})

        if not creators:
            creators = [{"name": "Unknown"}]

        title = str(metadata.get("title") or "").strip() or str(obj.get("id") or doi or "Untitled")
        fallback_publisher = ""
        if has_app_context():
            fallback_publisher = str(
                current_app.config.get("APP_RDM_ADMIN_EMAIL_RECIPIENT") or ""
            ).strip()

        publisher = (
            str(metadata.get("publisher") or "").strip()
            or fallback_publisher
            or "Unknown publisher"
        )

        payload = {
            "creators": creators,
            "titles": [{"title": title}],
            "publisher": publisher,
            "publicationYear": self._publication_year(metadata),
            # Required by DataCite JSON API v4.x, use the safest fallback.
            "types": {"resourceTypeGeneral": "Other"},
        }

        # DataCite's "Identifier" maps to DOI in the JSON API payload.
        if doi:
            payload["doi"] = doi

        return payload



