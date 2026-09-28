"""Script to import a subset of the ProQuest dissertations stored on Box.

Make sure the Invenio services have been set up and are running.

Files are taken from the Box folder "ProQuest Dissertations Metadata" and matched
to records in the ProQuest MARCXML export by ProQuest publication number (MARC 001
without its "AAI" prefix, e.g. AAI0001798 -> 0001798, AAIT-00038 -> T-00038). A Box
file belongs to a record when its name contains that publication number, ignoring
case and separators (T-00038, T00038 and T_00038 all match). Only records that have at
least one matching Box file are imported. Records with a MARC 506 restriction note
(withdrawn or embargoed by ProQuest) are skipped.

The user used will become the record owner for all imported records.

The Box developer token is read from the BOX_DEVELOPER_TOKEN environment variable.

To run the script, go to the repository root directory and use the following command:

        $ export BOX_DEVELOPER_TOKEN=<token>
        $ pipenv run python site/chicago_invenio/scripts/import_ss.py <email> <datafile> [--community <uuid>] [--max-records <n>]

(Run it with python, not "invenio shell": IPython swallows the --options. The script creates its own app context.)

Where:

    email: Email of the user to assign as record owner
    datafile: Path to the ProQuest MARCXML data file, e.g. "tmp/import/UChicago DAAP MARCXMLData.xml"

By default records are assigned to communities by the community assignment algorithm.
Pass --community <uuid> to put every imported record in that community instead.
"""
import csv
import json
import os
import re
import sys
import tempfile
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

import click
from box_sdk_gen import BoxClient, BoxDeveloperTokenAuth
from flask import current_app
from invenio_access.permissions import system_identity
from invenio_app.factory import create_app
from invenio_communities.proxies import current_communities
from invenio_rdm_records.proxies import (
    current_rdm_records_service,
    current_record_communities_service,
)
from invenio_requests.proxies import current_requests_service
from load_as_coms_colls import main as get_create_community_collection_structure, CSV
from chicago_invenio.scripts.community_assignment_algorithm import CommunityAssignmentAlgorithm
from chicago_invenio.scripts.utils import get_identity_with_roles
from import_data import (
    MARC_NS,
    logger,
    parse_personal_name_from_text,
    stream_marc_records,
)

FOLDER_NAME = 'ProQuest Dissertations Metadata'

# Publication numbers in file names: 0001798, T-00038, TM12345, TR12345, optionally prefixed by AAI
PUB_NUMBER_PATTERN = re.compile(r'(?<![0-9A-Z])(?:AAI)?(TM|TR|T)?[-_ ]?(\d{5,})(?![0-9])')

# ProQuest placeholders in MARC 520, e.g. "Abstract Not Available.", "No abstract available."
PLACEHOLDER_ABSTRACT_PATTERN = re.compile(
    r'^\W*(no\s+)?abstract\s+(not\s+)?(available|found|unavailable)\W*$', re.IGNORECASE
)

# Language names used in MARC 546 mapped to ISO 639-3
LANGUAGE_NAMES = {
    'english': 'eng',
    'french': 'fra',
    'spanish': 'spa',
    'german': 'deu',
    'italian': 'ita',
    'portuguese': 'por',
    'russian': 'rus',
    'chinese': 'zho',
    'japanese': 'jpn',
    'hebrew': 'heb',
    'latin': 'lat',
}

# Placeholder, misspelt and inconsistently punctuated degrees in MARC 791 / 502$b
DEGREE_CORRECTIONS = {
    'xx': None,
    'PDH': 'Ph.D.',
    'SM': 'S.M.',
    'BD': 'B.D.',
    'D.Comp.L': 'D.Comp.L.',
}

# Degrees (MARC 791 / 502$b) that make a record a dissertation rather than a thesis
DOCTORAL_DEGREE_PREFIXES = ('ph.d', 'd.', 'educat.d', 'j.s.d', 'm.d')

RESULTS_FILE = 'import_ss_results.csv'
ERRORS_FILE = 'import_ss_errors.json'


# ==================== BOX ====================

def get_all_items(client: BoxClient, folder_id: str):
    marker = None
    while True:
        page = client.folders.get_folder_items(
            folder_id, usemarker=True, marker=marker, limit=1000
        )
        yield from page.entries
        marker = page.next_marker
        if not marker:
            break


def build_box_file_index(client: BoxClient) -> Dict[str, List]:
    """Map ProQuest publication numbers to the Box files whose names contain them."""
    folder = next(
        (item for item in get_all_items(client, '0')
         if item.type == 'folder' and item.name == FOLDER_NAME),
        None
    )
    if folder is None:
        raise ValueError(f"Box folder '{FOLDER_NAME}' not found")

    index = defaultdict(list)
    file_count = 0
    for item in get_all_items(client, folder.id):
        if item.type != 'file':
            continue
        file_count += 1
        keys = {prefix + digits for prefix, digits in PUB_NUMBER_PATTERN.findall(item.name.upper())}
        if not keys:
            logger.warning(f"No publication number found in Box file name '{item.name}'")
        for key in keys:
            index[key].append(item)

    logger.info(f"Found {file_count} files in Box folder '{FOLDER_NAME}'")
    return index


def download_box_file(client: BoxClient, item, dest_dir: str) -> str:
    path = os.path.join(dest_dir, item.name)
    with open(path, 'wb') as f:
        client.downloads.download_file_to_output_stream(item.id, f)
    return path


# ==================== MARC ====================

def normalize_pub_number(pub_number: str) -> str:
    """Normalize a publication number for matching: AAIT-00038 / T-00038 / t00038 -> T00038."""
    return re.sub(r'[^0-9A-Z]', '', re.sub(r'^AAI', '', pub_number.strip().upper()))


def get_pub_number(record_elem) -> Optional[str]:
    control_001 = record_elem.find('.//marc:controlfield[@tag="001"]', MARC_NS)
    if control_001 is None or not control_001.text:
        return None
    return re.sub(r'^AAI', '', control_001.text.strip())


def subfield_text(field, code: str) -> Optional[str]:
    subfield = field.find(f'.//marc:subfield[@code="{code}"]', MARC_NS)
    if subfield is None or not subfield.text or not subfield.text.strip():
        return None
    return subfield.text.strip()


def field_values(record_elem, tag: str, code: str = 'a') -> List[str]:
    values = []
    for field in record_elem.findall(f'.//marc:datafield[@tag="{tag}"]', MARC_NS):
        value = subfield_text(field, code)
        if value:
            values.append(value)
    return values


def clean(text: str) -> str:
    """Strip ISBD punctuation (trailing ' /', ',', '.', ':') from a MARC value."""
    return re.sub(r'\s*[/,:;.]+$', '', text.strip())


def parse_proquest_record(record_elem, pub_number: str) -> Dict[str, Any]:
    """Convert a ProQuest MARCXML record to InvenioRDM format."""
    metadata = {'publisher': "University of Chicago"}
    custom_fields = {}

    # ==================== RESOURCE TYPE ====================

    degree = (field_values(record_elem, '791') or [None])[0]
    thesis_field = record_elem.find('.//marc:datafield[@tag="502"]', MARC_NS)
    if not degree and thesis_field is not None:
        degree = subfield_text(thesis_field, 'b')

    if degree in DEGREE_CORRECTIONS:
        degree = DEGREE_CORRECTIONS[degree]

    if degree and degree.lower().startswith(DOCTORAL_DEGREE_PREFIXES):
        metadata['resource_type'] = {'id': 'publication-dissertation'}
    else:
        metadata['resource_type'] = {'id': 'publication-thesis'}

    if degree:
        custom_fields['thesis:thesis'] = {'type': degree}

    # ==================== CREATORS ====================

    creators = []
    for tag in ('100', '700'):
        for name_field in record_elem.findall(f'.//marc:datafield[@tag="{tag}"]', MARC_NS):
            name = subfield_text(name_field, 'a')
            creator = parse_personal_name_from_text(clean(name)) if name else None
            if creator:
                creators.append(creator)
    metadata['creators'] = creators

    # ==================== CONTRIBUTORS (ADVISORS) ====================

    advisor_names = [clean(name) for name in field_values(record_elem, '720')]
    if not advisor_names:
        # Older records only list advisors in a note, e.g. "Advisors: Friedrich, Paul; Turner, Terrence."
        for note in field_values(record_elem, '500'):
            if note.startswith('Advisors:'):
                advisor_names = [clean(name) for name in note[len('Advisors:'):].split(';') if name.strip()]

    contributors = []
    for name in advisor_names:
        contributor = parse_personal_name_from_text(name)
        if contributor:
            contributor['role'] = {'id': 'supervisor'}
            contributors.append(contributor)
    if contributors:
        metadata['contributors'] = contributors

    # ==================== TITLE ====================

    title_field = record_elem.find('.//marc:datafield[@tag="245"]', MARC_NS)
    title = None
    if title_field is not None:
        title_parts = [subfield_text(title_field, code) for code in ('a', 'b')]
        title = clean(' '.join(clean(part) for part in title_parts if part))
    metadata['title'] = title or "Untitled"

    # ==================== DATE ====================

    date_candidates = field_values(record_elem, '792') + field_values(record_elem, '264', 'c')
    if thesis_field is not None and subfield_text(thesis_field, 'd'):
        date_candidates.append(subfield_text(thesis_field, 'd'))
    for candidate in date_candidates:
        year = re.search(r'\b(\d{4})\b', candidate)
        if year:
            metadata['publication_date'] = year.group(1)
            break

    # ==================== LANGUAGE ====================

    # 008/35-37 is "eng" for every record in the ProQuest export, so use the 546 language note
    languages = []
    for language in field_values(record_elem, '546'):
        lang_code = LANGUAGE_NAMES.get(clean(language).lower())
        if lang_code:
            languages.append({'id': lang_code})
        else:
            logger.warning(f"Unknown language '{language}' in record AAI{pub_number}")
    if languages:
        metadata['languages'] = languages

    # ==================== DESCRIPTION ====================

    abstracts = [abstract for abstract in field_values(record_elem, '520')
                 if not PLACEHOLDER_ABSTRACT_PATTERN.match(abstract)]
    if abstracts:
        metadata['description'] = '\n\n'.join(abstracts)

    # ==================== SUBJECTS ====================

    subjects = []
    seen_subjects = set()
    for term in field_values(record_elem, '650') + field_values(record_elem, '653'):
        term = clean(term)
        # Single characters are fragments of keywords ProQuest split at apostrophes, e.g. "S"
        if len(term) > 1 and term.lower() not in seen_subjects:
            seen_subjects.add(term.lower())
            subjects.append({'subject': term})
    if subjects:
        metadata['subjects'] = subjects

    # ==================== IDENTIFIERS ====================

    isbns = field_values(record_elem, '020')
    if isbns:
        metadata['identifiers'] = [{'identifier': isbn, 'scheme': 'isbn'} for isbn in isbns]

    # Page count (MARC 300) is not imported: 71% of records have a "(0 page)" or "(1 page)" placeholder

    # ==================== RIGHTS ====================

    # Required custom field, set the same way as import_data.py
    metadata['rights'] = [{
        'identifier': "https://knowledge.uchicago.edu/pages/?page=Distribution+License&ln=en",
        'title': {'en': 'Distribution License'}
    }]
    custom_fields['chicago:distribution_license'] = "I agree"

    record = {
        'metadata': metadata,
        'files': {'enabled': True},
        'access': {
            'record': 'public',
            'files': 'public'
        },
    }
    if custom_fields:
        record['custom_fields'] = custom_fields

    return record


# ==================== INVENIO ====================

def add_files_to_draft(draft, identity, file_paths: List[str]):
    draft_file_service = current_rdm_records_service.draft_files
    keys = [os.path.basename(path) for path in file_paths]

    draft_file_service.init_files(identity, draft.id, data=[{'key': key} for key in keys])
    for key, path in zip(keys, file_paths):
        with open(path, 'rb') as f:
            draft_file_service.set_file_content(identity, draft.id, key, f)
        draft_file_service.commit_file(identity, draft.id, key)

    logger.info(f"Uploaded {len(keys)} files to draft {draft.id}: {keys}")


def get_default_preview(file_paths: List[str]) -> Optional[str]:
    pdfs = [os.path.basename(path) for path in file_paths if path.lower().endswith('.pdf')]
    return pdfs[0] if pdfs else None


def add_to_community(published, identity, community_id: str, community_label: str):
    try:
        request_id = current_record_communities_service.add(
            identity,
            published.id,
            dict(communities=[dict(id=community_id, require_review=False)]),
        )[0][0]["request_id"]
        current_requests_service.execute_action(identity, request_id, "accept")
        logger.info(f"Added record {published.id} to community '{community_label}'")
    except Exception as community_error:
        logger.warning(f"Failed to add record {published.id} to community '{community_label}': {community_error}")


def assign_communities(published, invenio_data, identity, community_map, community_algorithm):
    resource_type = invenio_data['metadata']['resource_type']['id']
    assignment_result = community_algorithm.assign_communities(
        divisions=[],
        departments=[],
        centers=[],
        resource_type=resource_type
    )

    for community_name in assignment_result.get('communities', []):
        if community_name not in community_map:
            logger.warning(f"Community '{community_name}' not found in community_map")
            continue
        add_to_community(published, identity, community_map[community_name], community_name)


def import_record(record_elem, pub_number: str, box_files: List, box_client: BoxClient,
                  identity, community_map, community_algorithm, community_override=None) -> str:
    invenio_data = parse_proquest_record(record_elem, pub_number)

    with tempfile.TemporaryDirectory() as tmp_dir:
        file_paths = [download_box_file(box_client, item, tmp_dir) for item in box_files]

        draft = current_rdm_records_service.create(data=invenio_data, identity=identity)
        try:
            add_files_to_draft(draft, identity, file_paths)

            default_preview = get_default_preview(file_paths)
            if default_preview:
                invenio_data['files']['default_preview'] = default_preview
                current_rdm_records_service.update_draft(identity=identity, id_=draft.id, data=invenio_data)

            # Publish using system_identity to bypass the curation workflow.
            # Ownership is already set by the draft creation above.
            published = current_rdm_records_service.publish(id_=draft.id, identity=system_identity)
        except Exception:
            # Don't leave a half-imported draft (and its files) behind
            try:
                current_rdm_records_service.delete_draft(system_identity, draft.id)
                logger.info(f"Deleted draft {draft.id} for AAI{pub_number} after failed import")
            except Exception as delete_error:
                logger.warning(f"Could not delete draft {draft.id} for AAI{pub_number}: {delete_error}")
            raise

    if community_override:
        add_to_community(published, identity, community_override['id'], community_override['slug'])
    elif community_algorithm:
        assign_communities(published, invenio_data, identity, community_map, community_algorithm)

    return published.id


@click.command("import_ss")
@click.argument("email")
@click.argument("data")
@click.option("--id_list", default=None, help="File of ProQuest publication numbers to import (one per line)")
@click.option("--max-records", "--max_records", "max_records", default=10, type=int,
              help="Maximum number of records to import")
@click.option("--community", "community_id", default=None,
              help="UUID of a community to add every imported record to, instead of using the community assignment algorithm")
def import_ss(email: str, data: str, id_list: Optional[str], max_records: int, community_id: Optional[str]):
    """Import a subset of the ProQuest dissertations on Box into Chicago Invenio."""
    token = os.environ.get('BOX_DEVELOPER_TOKEN')
    if not token:
        click.secho("Set the BOX_DEVELOPER_TOKEN environment variable.", fg="red")
        sys.exit(1)

    limit_to_pub_numbers = None
    if id_list is not None:
        with open(id_list, encoding='utf-8-sig') as f:
            limit_to_pub_numbers = {
                normalize_pub_number(line)
                for line in f if line.strip()
            }
        logger.info(f"Using id list {id_list} ({len(limit_to_pub_numbers)} publication numbers)")

    app = create_app()
    with app.app_context():
        user_datastore = current_app.extensions["security"].datastore
        owner = user_datastore.find_user(email=email)
        if not owner:
            click.secho(f"User with email {email} not found.", fg="red")
            sys.exit(1)

        identity = get_identity_with_roles(owner)

        community_override = None
        community_map = {}
        community_algorithm = None
        if community_id:
            # Fail before importing anything if the community doesn't exist
            try:
                community = current_communities.service.read(system_identity, community_id)
            except Exception as e:
                click.secho(f"Community {community_id} not found: {e}", fg="red")
                sys.exit(1)
            community_override = {'id': community.id, 'slug': community.data['slug']}
            logger.info(f"Adding all records to community '{community.data['slug']}' ({community.id})")
        else:
            community_map = get_create_community_collection_structure(identity)
            try:
                community_algorithm = CommunityAssignmentAlgorithm(CSV)
            except Exception as e:
                logger.error(f"Failed to initialize community assignment algorithm: {e}")

        box_client = BoxClient(auth=BoxDeveloperTokenAuth(token=token))
        box_index = build_box_file_index(box_client)

        logger.info(f"Starting ProQuest import for user: {email}")
        logger.info(f"Data file: {data}")
        logger.info(f"Max records: {max_records}")

        start_time = time.time()
        total_matched = 0
        total_created = 0
        total_skipped_restricted = 0
        errors = []

        with open(RESULTS_FILE, 'w', newline='', encoding='utf-8') as results_file:
            results = csv.writer(results_file)
            results.writerow(['pub_number', 'record_id', 'files'])

            for record_elem in stream_marc_records(data):
                if total_matched >= max_records:
                    logger.info(f"Reached maximum records limit: {max_records}")
                    break

                pub_number = get_pub_number(record_elem)
                if pub_number is None:
                    continue
                key = normalize_pub_number(pub_number)
                if limit_to_pub_numbers is not None and key not in limit_to_pub_numbers:
                    continue
                box_files = box_index.get(key)
                if not box_files:
                    continue
                restriction_notes = field_values(record_elem, '506')
                if restriction_notes:
                    # Withdrawn/embargoed by ProQuest; left out until a rights decision is made
                    total_skipped_restricted += 1
                    logger.info(f"Skipping restricted record AAI{pub_number}: {'; '.join(restriction_notes)}")
                    continue

                total_matched += 1
                file_names = [item.name for item in box_files]
                try:
                    record_id = import_record(record_elem, pub_number, box_files, box_client,
                                              identity, community_map, community_algorithm,
                                              community_override)
                    total_created += 1
                    results.writerow([pub_number, record_id, '|'.join(file_names)])
                    logger.info(f"Imported AAI{pub_number} as {record_id} with files {file_names}")
                except Exception as e:
                    logger.exception(f"Error importing AAI{pub_number}: {e}")
                    errors.append({
                        'pub_number': pub_number,
                        'files': file_names,
                        'error_message': str(e),
                        'validation_errors': getattr(e, 'messages', None) or getattr(e, 'errors', None),
                    })

        elapsed_time = time.time() - start_time
        logger.info("=" * 50)
        logger.info("IMPORT COMPLETE")
        logger.info(f"Records with Box files processed: {total_matched}")
        logger.info(f"Records created: {total_created}")
        logger.info(f"Restricted records skipped (MARC 506): {total_skipped_restricted}")
        logger.info(f"Time taken: {elapsed_time:.2f} seconds")
        logger.info(f"Results written to {RESULTS_FILE}")
        if errors:
            with open(ERRORS_FILE, 'w', encoding='utf-8') as f:
                json.dump(errors, f, indent=2, ensure_ascii=False, default=str)
            logger.info(f"Wrote {len(errors)} errors to {ERRORS_FILE}")
        logger.info("=" * 50)


if __name__ == '__main__':
    import_ss()
