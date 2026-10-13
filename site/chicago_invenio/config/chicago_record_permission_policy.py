# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 University of Chicago.
#
# Chicago-Invenio is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.

"""Custom record permission policy for Chicago Invenio.

This policy prevents non-admin users from editing published records
or creating new versions. Only administrators and community curators
can perform these actions.
"""

from itertools import chain

from flask import g, has_request_context, request
from invenio_curations.services.generators import IfCurationRecordBasedExists
from invenio_curations.services.permissions import CurationRDMRecordPermissionPolicy
from invenio_rdm_records.services.generators import (
    AccessGrant,
    IfDeleted,
    IfExternalDOIRecord,
    RecordCommunitiesAction,
    SecretLinks,
)
from invenio_records_permissions.generators import Disable, IfConfig, SystemProcess


class ChicagoRDMRecordPermissionPolicy(CurationRDMRecordPermissionPolicy):
    """Custom RDM record policy for Chicago Invenio.

    This policy restricts editing and versioning of published records
    to administrators and community curators only. Regular record owners
    cannot edit or create new versions after publication.
    """

    # Redefine can_manage WITHOUT RecordOwners() - only allow:
    # - Community curators (via RecordCommunitiesAction)
    # - Users with explicit "manage" access grants
    # - System processes
    # - Administrators (added implicitly by invenio_access)
    can_manage_no_owner = [
        RecordCommunitiesAction("curate"),
        AccessGrant("manage"),
        SystemProcess(),
    ]

    # can_curate without record owners
    can_curate_no_owner = can_manage_no_owner + [
        AccessGrant("edit"),
        SecretLinks("edit"),
    ]

    # Override can_edit: Only admins/curators can edit published records
    # RecordOwners() is excluded, so regular owners cannot edit after publish
    can_edit = [IfDeleted(then_=[Disable()], else_=can_curate_no_owner)]

    # Override can_new_version: Only admins/curators can create new versions
    # RecordOwners() is excluded, so regular owners cannot create new versions
    can_new_version = [
        IfConfig(
            "RDM_ALLOW_EXTERNAL_DOI_VERSIONING",
            then_=can_curate_no_owner,
            else_=[IfExternalDOIRecord(then_=[SystemProcess()], else_=can_curate_no_owner)],
        ),
    ]


# IfCurationRecordBasedExists searches the requests index (plus several SQL
# lookups) on every evaluation, and serializing one record evaluates it ~7 times
# across can_read, can_view, can_read_files, links, etc. That made the 10-record
# front-page list take ~5 s. Patch the condition to:
# - skip the lookup when the current identity cannot match any `then_` need
#   (only curation moderators benefit from a positive result; with an empty
#   `else_`, as in all invenio-curations policies, skipping can only deny);
# - remember the answer per record for the rest of a GET request (reads cannot
#   create curation requests, so it cannot go stale within the request).
_uncached_curation_condition = IfCurationRecordBasedExists._condition


def _fast_curation_condition(self, record=None, **kwargs):
    """Check for a curation request only when it can affect the outcome."""
    if record is None or not has_request_context():
        return _uncached_curation_condition(self, record=record, **kwargs)

    identity = getattr(g, "identity", None)
    if identity is not None and not self.else_:
        then_needs = set(
            chain.from_iterable(gen.needs(record=record) for gen in self.then_)
        )
        if not then_needs & identity.provides:
            return False

    if request.method != "GET":
        return _uncached_curation_condition(self, record=record, **kwargs)

    cache = g.setdefault("_curation_record_exists", {})
    key = (type(record).__name__, str(record.id))
    if key not in cache:
        cache[key] = _uncached_curation_condition(self, record=record, **kwargs)
    return cache[key]


IfCurationRecordBasedExists._condition = _fast_curation_condition
