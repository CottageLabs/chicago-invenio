from invenio_records_resources.services.custom_fields import BaseCF, BaseListCF
from invenio_records_resources.services.custom_fields.mappings import TextMapping
from marshmallow import fields, Schema, validate
from marshmallow_utils.fields import SanitizedUnicode


class RelatedItemIdentifierSchema(Schema):
    """Schema for a single related item identifier with scheme and identifier."""

    scheme = SanitizedUnicode(required=True, validate=validate.Length(min=1))
    identifier = SanitizedUnicode(required=True, validate=validate.Length(min=1))


class RelatedItemIdentifier(BaseCF):
    """Custom field for a single related item identifier object."""

    def __init__(self, name, value_as_filter=False, **kwargs) -> None:
        """Constructor."""
        super().__init__(name, **kwargs)
        self._value_as_filter = value_as_filter

    @property
    def field(self):
        """Return the marshmallow field."""
        return fields.Nested(RelatedItemIdentifierSchema)

    @property
    def mapping(self):
        """Return the mapping."""
        return {
            "properties": {
                "scheme": TextMapping(use_as_filter=self._value_as_filter).to_dict(),
                "identifier": TextMapping(use_as_filter=self._value_as_filter).to_dict(),
            }
        }


class RelatedItem(BaseListCF):
    """A related item with type, title, relation type, and identifier."""

    def __init__(self, name, value_as_filter=False, **kwargs) -> None:
        """Constructor."""
        super().__init__(
            name,
            field_cls=fields.Nested,
            field_args={
                "nested": {
                    "item_type": SanitizedUnicode(),
                    "title": SanitizedUnicode(),
                    "relation_type": SanitizedUnicode(),
                    "identifier": fields.Nested(RelatedItemIdentifierSchema),
                }
            },
            **kwargs,
        )
        self._value_as_filter = value_as_filter

    @property
    def mapping(self):
        """Return the mapping."""
        return {
            "properties": {
                "item_type": {"type": "text"},
                "relation_type": {"type": "text"},
                "title": TextMapping(use_as_filter=self._value_as_filter).to_dict(),
                "identifier": {
                    "properties": {
                        "scheme": TextMapping(use_as_filter=self._value_as_filter).to_dict(),
                        "identifier": TextMapping(use_as_filter=self._value_as_filter).to_dict(),
                    }
                },
            }
        }
