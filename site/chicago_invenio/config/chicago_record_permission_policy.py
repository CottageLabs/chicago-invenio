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
