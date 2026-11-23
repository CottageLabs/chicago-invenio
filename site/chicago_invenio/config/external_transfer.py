# -*- coding: utf-8 -*-
#
# Copyright (C) 2026 University of Chicago.
#
# Chicago-Invenio is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.

"""Remote file transfer for files held in external storage (e.g. DataHub).

The file is registered on the record with its URL, size and checksum, and
downloads are redirected to that URL. Unlike ``file.metadata``, the transfer
fields below are set when the file is initialised and cannot be changed with
a file metadata update.

Example file entry for ``POST /api/records/{id}/draft/files``::

    {
      "key": "data.csv",
      "size": 10737418240,
      "checksum": "md5:<md5-of-file>",
      "transfer": {
        "type": "R",
        "url": "https://<datahub-host>/files/data.csv",
        "location": "DataHub",
        "access_method": "globus"
      }
    }
"""

from flask import current_app
from flask_principal import RoleNeed
from invenio_records_permissions.generators import Generator
from invenio_records_resources.services.files.transfer import RemoteTransfer
from marshmallow import fields, validate

ACCESS_METHODS = ["standard", "globus"]


class ExternalTransferSchema(RemoteTransfer.Schema):
    """Remote transfer schema with the external location and access method."""

    location = fields.String(required=True, validate=validate.Length(min=1, max=100))
    access_method = fields.String(validate=validate.OneOf(ACCESS_METHODS))


class ExternalTransfer(RemoteTransfer):
    """Remote transfer (type ``R``) for files held in external storage.

    Replaces ``RemoteTransfer`` in ``RECORDS_RESOURCES_TRANSFERS``: only one
    class can be registered per transfer type.
    """

    Schema = ExternalTransferSchema


class ExternalFilesDepositor(Generator):
    """Users with the role named in ``CHICAGO_EXTERNAL_FILES_ROLE``.

    Intended for the service account of an external storage system (e.g.
    DataHub), which registers remote files on drafts.
    """

    def needs(self, **kwargs):
        """Enabling needs."""
        role = current_app.config.get("CHICAGO_EXTERNAL_FILES_ROLE")
        return [RoleNeed(role)] if role else []
