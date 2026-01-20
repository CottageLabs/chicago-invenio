from invenio_rdm_records.contrib.meeting import (
    MEETING_CUSTOM_FIELDS,
    MEETING_CUSTOM_FIELDS_UI, )
from invenio_rdm_records.contrib.meeting.custom_fields import MeetingCF
from functools import partial

from invenio_i18n import lazy_gettext as _
from invenio_rdm_records.services.schemas.metadata import _valid_url, record_identifiers_schemes
from marshmallow import fields
from marshmallow_utils.fields import IdentifierValueSet, SanitizedUnicode
from marshmallow_utils.schemas import IdentifierSchema


class MeetingCFOrganizer(MeetingCF):
    """Nested custom field."""

    @property
    def field(self):
        """Meeting fields definitions."""
        return fields.Nested(
            {
                "acronym": SanitizedUnicode(),
                "dates": SanitizedUnicode(),
                "place": SanitizedUnicode(),
                "organizer": SanitizedUnicode(), # Added organizer field
                "session_part": SanitizedUnicode(),
                "session": SanitizedUnicode(),
                "title": SanitizedUnicode(),
                "url": SanitizedUnicode(
                    validate=_valid_url(error_msg=_("You must provide a valid URL.")),
                ),
                "identifiers": IdentifierValueSet(
                    fields.Nested(
                        partial(
                            IdentifierSchema, allowed_schemes=record_identifiers_schemes
                        )
                    )
                ),
            }
        )

    @property
    def mapping(self):
        """Meeting search mappings."""
        return {
            "type": "object",
            "properties": {
                "acronym": {"type": "keyword"},
                "dates": {"type": "keyword"},
                "place": {"type": "text"},
                "organizer": {"type": "text"}, # Added organizer mapping
                "session_part": {"type": "keyword"},
                "session": {"type": "keyword"},
                "title": {
                    "type": "text",
                    "fields": {"keyword": {"type": "keyword"}},
                },
                "url": {"type": "keyword"},
                "identifiers": {
                    "type": "object",
                    "properties": {
                        "identifier": {"type": "keyword"},
                        "scheme": {"type": "keyword"},
                    },
                },
            },
        }

MEETING_ORG_CUSTOM_FIELDS = [
    MeetingCFOrganizer(name="meeting:meeting"),
]

MEETING_ORG_CUSTOM_FIELDS_UI = {
    "section": _("Conference"),
    "fields": [
        {
            "field": "meeting:meeting",
            "ui_widget": "MeetingOrganizer",
            "template": "meeting.html",
            "props": {
                "title": {
                    "label": _("Title"),
                    "placeholder": "",
                    "description": "",
                },
                "acronym": {
                    "label": _("Acronym"),
                    "placeholder": "",
                    "description": "",
                },
                "dates": {
                    "label": _("Dates"),
                    "placeholder": _("e.g. 21-22 November 2022."),
                    "description": "",
                },
                "place": {
                    "label": _("Place"),
                    "placeholder": "",
                    "description": _("Location where the conference took place."),
                },
                "organizer": {
                    "label": _("Organizer"),
                    "placeholder": "",
                    "description": _("The person who organized the conference."),
                },
                "url": {
                    "label": _("Website"),
                    "placeholder": "",
                    "description": "",
                },
                "session": {
                    "label": _("Session"),
                    "placeholder": _("e.g. VI"),
                    "description": _("Session within the conference."),
                },
                "session_part": {
                    "label": _("Part"),
                    "placeholder": _("e.g. 1"),
                    "description": _("Part within the session."),
                },
            },
        }
    ],
}