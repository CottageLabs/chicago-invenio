# -*- coding: utf-8 -*-
#
# Copyright (C) 2026 University of Chicago.
#
# Chicago-Invenio is free software; you can redistribute it and/or modify
# it under the terms of the MIT License; see LICENSE file for more details.

"""Celery tasks for the Chicago demo data.

The records are created by the worker, like the stock demo, so they run
after the vocabulary fixture tasks that setup has already queued.
"""

from celery import shared_task
from invenio_access.permissions import system_identity
from invenio_accounts.proxies import current_datastore
from invenio_curations.proxies import current_curations_service
from invenio_rdm_records.fixtures.tasks import _add_file_to_draft
from invenio_rdm_records.proxies import current_rdm_records
from invenio_rdm_records.requests import CommunitySubmission
from invenio_records.systemfields.relations.errors import InvalidRelationValue
from invenio_requests import current_requests_service

from chicago_invenio.scripts.utils import get_identity_with_roles

# The worker may run these alongside the last vocabulary fixture tasks, so a
# vocabulary entry can be missing. The failed draft creation is rolled back,
# so the task is safe to retry.
RETRY_MISSING_VOCABULARY = {
    "autoretry_for": (InvalidRelationValue,),
    "retry_backoff": 5,
    "max_retries": 8,
}


def get_identity(user_id):
    """Identity with roles for the given user."""
    return get_identity_with_roles(current_datastore.get_user(user_id))


def create_draft(identity, data, create_file):
    """Create a draft, with a file if the instance requires one."""
    service = current_rdm_records.records_service
    draft = service.create(identity, data)
    if create_file:
        _add_file_to_draft(service.draft_files, draft.id, "file.txt", identity)
    return draft


@shared_task(**RETRY_MISSING_VOCABULARY)
def create_demo_published_record(user_id, data, create_file, community_id):
    """Publish a record owned by the user and include it in a community."""
    draft = create_draft(get_identity(user_id), data, create_file)
    # System skips the curation and community-required checks on publish
    record = current_rdm_records.records_service.publish(system_identity, draft.id)
    current_rdm_records.record_communities_service.add(
        system_identity,
        record.id,
        {"communities": [{"id": community_id, "require_review": False}]},
    )


@shared_task(**RETRY_MISSING_VOCABULARY)
def create_demo_draft_in_review(user_id, data, create_file, community_id, actions):
    """Create a draft with a curation request, as the deposit form would.

    ``actions`` are then run on the curation request as the system. Accepting
    it also submits the community request (see ChicagoCurationAcceptAction).
    """
    identity = get_identity(user_id)
    draft = create_draft(identity, data, create_file)
    current_rdm_records.records_service.review.update(
        identity,
        draft.id,
        {"type": CommunitySubmission.type_id, "receiver": {"community": community_id}},
    )
    curation = current_curations_service.create(
        identity, {"topic": {"record": draft.id}}
    )
    for action in actions:
        current_requests_service.execute_action(system_identity, curation.id, action)
