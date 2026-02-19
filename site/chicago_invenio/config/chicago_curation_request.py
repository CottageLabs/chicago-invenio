# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 University of Chicago.
#
# Chicago-Invenio is free software; you can redistribute it and/or modify
# it under the terms of the MIT License; see LICENSE file for more details.

"""Custom curation accept action for Chicago Invenio.

This module provides a custom accept action that automatically submits
the record to the community after curation is approved.
"""

from flask import current_app
from flask_principal import Identity
from invenio_access.permissions import system_identity
from invenio_access.utils import get_identity
from invenio_curations.requests.curation import CurationAcceptAction
from invenio_records_resources.services.uow import UnitOfWork
from invenio_requests import current_events_service, current_requests_service
from invenio_requests.customizations.event_types import CommentEventType


class ChicagoCurationAcceptAction(CurationAcceptAction):
    """Accept curation and auto-submit to community.

    When a curation request is accepted, this action automatically
    submits the record to the selected community for review.
    The community curator still needs to approve the submission.
    """

    def execute(self, identity: Identity, uow: UnitOfWork) -> None:
        """Execute the accept action and auto-submit to community."""
        # Accept the curation request (sends notification, updates status)
        super().execute(identity, uow)

        # Check if auto-submit is enabled
        if not current_app.config.get("CHI_AUTO_SUBMIT_COMMUNITY_ON_CURATION", True):
            return

        # Resolve the draft from curation request topic
        draft = self.request.topic.resolve()

        # Get the community submission request
        community_submission = getattr(draft.parent, "review", None)
        if not community_submission:
            return

        # Get the request ID - handle both object and reference cases
        try:
            request_id = str(community_submission.request_id)
        except AttributeError:
            # May be a direct reference with an id attribute
            request_id = str(community_submission.id) if hasattr(community_submission, "id") else None

        if not request_id:
            return

        # Read the request to check its status
        try:
            request_record = current_requests_service.read(
                system_identity, request_id
            )
            status = request_record.data.get("status")
        except Exception:
            # If we can't read the request, don't proceed
            return

        # Only submit if the request is in "created" state (not yet submitted)
        if status != "created":
            return

        # Get the record owner's identity to submit on their behalf
        owner = draft.parent.access.owner.resolve()
        if not owner:
            # Fall back to system identity if owner cannot be resolved
            owner_identity = system_identity
        else:
            owner_identity = get_identity(owner)

        # Submit the community submission request as the record owner
        current_requests_service.execute_action(
            owner_identity,
            request_id,
            "submit",
            uow=uow,
        )

        # Add explanatory comment using the curator's identity
        current_events_service.create(
            identity,
            request_id,
            {
                "payload": {
                    "content": "Automatically submitted to community after curation approval."
                }
            },
            CommentEventType,
            uow=uow,
            notify=False,
        )
