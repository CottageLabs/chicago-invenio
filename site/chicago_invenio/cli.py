# -*- coding: utf-8 -*-
#
# Copyright (C) 2026 University of Chicago.
#
# Chicago-Invenio is free software; you can redistribute it and/or modify
# it under the terms of the MIT License; see LICENSE file for more details.

"""Chicago CLI commands.

Importing this module (via the ``flask.commands`` entry point) also replaces
``invenio rdm-records demo records``. The stock command publishes records
without a community, which fails with RDM_COMMUNITY_REQUIRED_TO_PUBLISH.
"""

import csv
import random

import click
from flask import current_app
from flask.cli import with_appcontext
from invenio_access.permissions import system_identity, system_process
from invenio_accounts.proxies import current_datastore
from invenio_curations.proxies import current_curations_service
from invenio_db import db
from invenio_rdm_records import cli as rdm_cli
from invenio_rdm_records.fixtures.demo import create_fake_record
from invenio_rdm_records.fixtures.tasks import _add_file_to_draft
from invenio_rdm_records.proxies import current_rdm_records
from invenio_rdm_records.requests import CommunitySubmission
from invenio_rdm_records.utils import get_or_create_user
from invenio_requests import current_requests_service

from chicago_invenio.scripts.utils import get_identity_with_roles, slugify

COMMUNITY_OWNER_EMAIL = "community@demo.org"
RECORD_CURATOR_EMAIL = "curator@demo.org"

# Curation request actions for the drafts in review, cycled through so there
# are drafts awaiting curation, under curation, and awaiting community review.
REVIEW_STAGES = [[], ["review"], ["review", "accept"]]


def get_user_with_role(email, role_name):
    """Get or create a demo user and make sure they have the given role."""
    user = get_or_create_user(email)
    role = current_datastore.find_or_create_role(role_name)
    current_datastore.add_role_to_user(user, role)
    db.session.commit()
    return user


def load_communities(identity):
    """Create the communities and collections from com_col_data.csv.

    The identity becomes the communities' owner. It is also given the system
    process need, as only the system may set ``children.allow``.

    Returns a map of community title to community ID.
    """
    # Imported here as it pulls in the app factory
    from chicago_invenio.scripts.load_as_coms_colls import main

    identity.provides.add(system_process)
    return main(identity)


def read_csv_rows():
    """Read the community/collection rules that have a community."""
    from chicago_invenio.scripts.load_as_coms_colls import CSV

    with open(CSV, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        next(reader)  # skip header
        rows = [row + [""] * (6 - len(row)) for row in reader]
    return [row for row in rows if row[4].strip()]


def fake_chicago_record(row):
    """Fake record whose fields match the collection query for a CSV row."""
    from chicago_invenio.scripts.load_as_coms_colls import RESOURCE_TYPE_MAP

    division, department, center, resource_type = (v.strip() for v in row[:4])

    data = create_fake_record()
    if resource_type:
        data["metadata"]["resource_type"] = {"id": RESOURCE_TYPE_MAP[resource_type]}

    custom_fields = {"chicago:distribution_license": "I agree"}
    if division:
        custom_fields["chicago:division"] = [{"id": slugify(division)}]
    if department:
        custom_fields["chicago:department"] = [{"id": slugify(department)}]
    if center:
        custom_fields["chicago:center_or_institute"] = [{"id": slugify(center)}]
    data["custom_fields"] = custom_fields

    create_file = not current_app.config.get("RDM_ALLOW_METADATA_ONLY_RECORDS")
    data["files"]["enabled"] = create_file
    return data, create_file


def create_draft(identity, data, create_file):
    """Create a draft, with a file if the instance requires one."""
    service = current_rdm_records.records_service
    draft = service.create(identity, data)
    if create_file:
        _add_file_to_draft(service.draft_files, draft.id, "file.txt", identity)
    return draft


def create_published_record(identity, data, create_file, community_id):
    """Publish a record owned by the demo user and include it in a community."""
    draft = create_draft(identity, data, create_file)
    # System skips the curation and community-required checks on publish
    record = current_rdm_records.records_service.publish(system_identity, draft.id)
    current_rdm_records.record_communities_service.add(
        system_identity,
        record.id,
        {"communities": [{"id": community_id, "require_review": False}]},
    )


def create_draft_in_review(identity, data, create_file, community_id, actions):
    """Create a draft with a curation request, as the deposit form would.

    ``actions`` are then run on the curation request as the system. Accepting
    it also submits the community request (see ChicagoCurationAcceptAction).
    """
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


@click.command("records")
@click.option(
    "-u",
    "--user",
    "user_email",
    default=rdm_cli.USER_EMAIL,
    show_default=True,
    help="E-mail of the depositor; created if it doesn't exist.",
)
@click.option(
    "-r",
    "--records",
    "n_records",
    default=100,
    show_default=True,
    help="Number of published records to create.",
)
@click.option(
    "--in-review",
    "n_in_review",
    default=10,
    show_default=True,
    help="Number of drafts to leave in curation / community review.",
)
@with_appcontext
def demo_records(user_email, n_records, n_in_review):
    """Create Chicago communities, collections and demo records."""
    depositor = get_or_create_user(user_email)
    owner = get_user_with_role(
        COMMUNITY_OWNER_EMAIL, current_app.config["COMMUNITY_CREATOR_ROLE"]
    )
    get_user_with_role(
        RECORD_CURATOR_EMAIL, current_app.config["CURATIONS_MODERATION_ROLE"]
    )

    click.secho("Creating communities and collections...", fg="green")
    community_map = load_communities(get_identity_with_roles(owner))

    rows = [row for row in read_csv_rows() if row[4].strip() in community_map]
    if not rows:
        raise click.ClickException("No communities were loaded.")
    identity = get_identity_with_roles(depositor)
    failures = 0

    click.secho(f"Creating {n_records} published records...", fg="green")
    for _ in range(n_records):
        row = random.choice(rows)
        data, create_file = fake_chicago_record(row)
        try:
            create_published_record(
                identity, data, create_file, community_map[row[4].strip()]
            )
        except Exception as e:
            failures += 1
            click.secho(f"Failed to create record for {row[4]}: {e!r}", fg="red")

    click.secho(f"Creating {n_in_review} drafts in review...", fg="green")
    for i in range(n_in_review):
        row = random.choice(rows)
        data, create_file = fake_chicago_record(row)
        try:
            create_draft_in_review(
                identity,
                data,
                create_file,
                community_map[row[4].strip()],
                REVIEW_STAGES[i % len(REVIEW_STAGES)],
            )
        except Exception as e:
            failures += 1
            click.secho(f"Failed to create draft for {row[4]}: {e!r}", fg="red")

    colour = "yellow" if failures else "green"
    click.secho(f"Demo records created ({failures} failures).", fg=colour)


# Replace the stock subcommand, and the bare `demo` fallback which invokes
# the module-level `records` directly.
rdm_cli.demo.add_command(demo_records, "records")
rdm_cli.records = demo_records


@click.group()
def chicago():
    """Chicago Invenio commands."""


@chicago.command("communities")
@click.option(
    "-u",
    "--user",
    "user_email",
    required=True,
    help="E-mail of an existing user with the community creator or admin role, "
    "who will own the communities.",
)
@with_appcontext
def communities(user_email):
    """Create the communities and collections from com_col_data.csv."""
    owner = current_datastore.get_user_by_email(user_email)
    if not owner:
        raise click.ClickException(f"User with email {user_email} not found.")
    community_map = load_communities(get_identity_with_roles(owner))
    click.secho(f"{len(community_map)} communities loaded.", fg="green")
