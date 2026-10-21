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
Like the stock command, the records are created by Celery tasks.
"""

import csv
import random

import click
from flask import current_app
from flask.cli import with_appcontext
from invenio_access.permissions import system_process
from invenio_accounts.proxies import current_datastore
from invenio_db import db
from invenio_rdm_records import cli as rdm_cli
from invenio_rdm_records.fixtures.demo import create_fake_record
from invenio_rdm_records.utils import get_or_create_user

from chicago_invenio.scripts.utils import get_identity_with_roles, slugify
from chicago_invenio.tasks import (
    create_demo_draft_in_review,
    create_demo_published_record,
)

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
    # The stock funder isn't in Chicago's funders vocabulary
    data["metadata"]["funding"] = [{"funder": {"id": "021nxhr62"}}]
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

    click.secho(f"Submitting {n_records} published record tasks...", fg="green")
    for _ in range(n_records):
        row = random.choice(rows)
        data, create_file = fake_chicago_record(row)
        create_demo_published_record.delay(
            depositor.id, data, create_file, community_map[row[4].strip()]
        )

    click.secho(f"Submitting {n_in_review} draft in review tasks...", fg="green")
    for i in range(n_in_review):
        row = random.choice(rows)
        data, create_file = fake_chicago_record(row)
        create_demo_draft_in_review.delay(
            depositor.id,
            data,
            create_file,
            community_map[row[4].strip()],
            REVIEW_STAGES[i % len(REVIEW_STAGES)],
        )

    click.secho("Demo records tasks submitted...", fg="green")


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
