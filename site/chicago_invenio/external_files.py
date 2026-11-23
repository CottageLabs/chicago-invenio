# -*- coding: utf-8 -*-
#
# Copyright (C) 2026 University of Chicago.
#
# Chicago-Invenio is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.

"""Landing page support for files held in external storage (issue #78).

Remote files (transfer type "R") redirect to another host and cannot be
previewed, so they are left out when the landing page picks a file to preview.
"""

from invenio_app_rdm.records_ui.views.filters import (
    has_previewable_files as rdm_has_previewable_files,
)
from invenio_app_rdm.records_ui.views.filters import (
    select_preview_file as rdm_select_preview_file,
)
from invenio_records_resources.services.files.transfer import REMOTE_TRANSFER_TYPE


def is_remote_file(file):
    """Whether a dumped file entry is a remote file."""
    return (file.get("transfer") or {}).get("type") == REMOTE_TRANSFER_TYPE


def local_files(files):
    """The file entries that are not remote files."""
    return [f for f in files or [] if not is_remote_file(f)]


def has_previewable_files(files):
    """Like the RDM filter, ignoring remote files."""
    return rdm_has_previewable_files(local_files(files))


def select_preview_file(files, default_preview=None):
    """Like the RDM filter, ignoring remote files."""
    return rdm_select_preview_file(local_files(files), default_preview=default_preview)


def finalize_app(app):
    """Replace the RDM preview filters.

    Runs after all blueprints, including invenio-app-rdm's which registers the
    filters being replaced, have been registered.
    """
    app.jinja_env.filters.update(
        has_previewable_files=has_previewable_files,
        select_preview_file=select_preview_file,
        has_remote_files=lambda files: any(is_remote_file(f) for f in files or []),
    )
