"""Script to import XML bibliographic data for the Chicago Invenio repository.

Make sure the Invenio services have been set up and are running.

Efficiently processes large MARCXML files using streaming XML parsing.

To run the script, go to the repository root directory and use the following command:

        $ pipenv run invenio shell site/chicago_invenio/scripts/xml_import_data.py <email> <filepath>
"""

import logging
import sys
import time
from typing import Dict, Any, Optional, Generator
import xml.etree.ElementTree as ET
from itertools import islice
import re

import click
import idutils
import requests
from flask import current_app
from invenio_app.factory import create_app
from invenio_rdm_records.fixtures.tasks import get_authenticated_identity
from invenio_rdm_records.proxies import current_rdm_records_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('output.log'),
        logging.StreamHandler()  # Also log to console
    ]
)
logger = logging.getLogger(__name__)

# Global counter for creator sources
creator_source_counts = {
    '100': 0,
    '110': 0,
    '700/710 (promoted)': 0,
    '701-713 (promoted)': 0,
    '245$c': 0,
    'Unknown': 0
}

# Global counter for publication date sources
date_source_counts = {
    '264$c': 0,
    '260$c': 0,
    '260$g (manufacture)': 0,
    '269$a': 0,
    '008 (positions 7-14)': 0,
    '264$c (copyright)': 0,
    '046$k': 0,
    'DOI scraping': 0,
    'DOI volume mapping': 0,
    'missing': 0
}

# Global counter for additional description sources
additional_description_source_counts = {
    '520$b': 0,
    '500': 0,
    '590': 0,
    '591': 0,
    '593': 0,
    '594': 0
}

# Counter for records with additional descriptions but no main description
records_with_additional_but_no_main_description = 0

# Track resource types for records missing main descriptions
resource_types_missing_main_description = {}

# MARC namespace
MARC_NS = {'marc': 'http://www.loc.gov/MARC21/slim'}

# MARC to InvenioRDM field mappings
RESOURCE_TYPE_MAPPINGS = {
    'thesis': 'publication-thesis',
    'dissertation': 'publication-dissertation',
    'article': 'publication-article',
    'book': 'publication-book',
    'book chapter': 'publication-section',
    'report': 'publication-report',
    'dataset': 'dataset',
    'software': 'software',
    'patent': 'publication-patent',
    'presentation': 'presentation',
}

CONTRIBUTOR_ROLE_MAPPINGS = {
    'advisor': 'supervisor',
    'committee member': 'supervisor',
    'editor': 'editor',
    'translator': 'translator',
    'author': 'author'
}

# ISO 639-1 to ISO 639-3 language code mappings
LANGUAGE_MAPPINGS = {
    'en': 'eng',  # English
    'es': 'spa',  # Spanish
    'fr': 'fra',  # French
    'de': 'deu',  # German
    'it': 'ita',  # Italian
    'pt': 'por',  # Portuguese
    'ru': 'rus',  # Russian
    'zh': 'zho',  # Chinese
    'ja': 'jpn',  # Japanese
    'ko': 'kor',  # Korean
    'ar': 'ara',  # Arabic
    'hi': 'hin',  # Hindi
    'nl': 'nld',  # Dutch
    'sv': 'swe',  # Swedish
    'no': 'nor',  # Norwegian
    'da': 'dan',  # Danish
    'fi': 'fin',  # Finnish
    'pl': 'pol',  # Polish
    'cs': 'ces',  # Czech
    'sk': 'slk',  # Slovak
    'hu': 'hun',  # Hungarian
    'ro': 'ron',  # Romanian
    'bg': 'bul',  # Bulgarian
    'hr': 'hrv',  # Croatian
    'sr': 'srp',  # Serbian
    'sl': 'slv',  # Slovenian
    'lv': 'lav',  # Latvian
    'lt': 'lit',  # Lithuanian
    'et': 'est',  # Estonian
    'he': 'heb',  # Hebrew
    'th': 'tha',  # Thai
    'vi': 'vie',  # Vietnamese
    'tr': 'tur',  # Turkish
    'el': 'ell',  # Greek
    'ca': 'cat',  # Catalan
    'eu': 'eus',  # Basque
    'ga': 'gle',  # Irish
    'cy': 'cym',  # Welsh
    'is': 'isl',  # Icelandic
    'mt': 'mlt',  # Maltese
    'la': 'lat',  # Latin
    'sa': 'san',  # Sanskrit
}

LICENSE_MAPPINGS = {
    'cc by': 'cc-by-4.0',
    'cc by-sa': 'cc-by-sa-4.0',
    'cc by-nc': 'cc-by-nc-4.0',
    'cc by-nc-sa': 'cc-by-nc-sa-4.0',
    'cc by-nd': 'cc-by-nd-4.0',
    'cc by-nc-nd': 'cc-by-nc-nd-4.0',
    'cc0': 'cc0-1.0'
}


def parse_personal_name_from_text(name_text: str) -> Dict[str, Any]:
    """Parse a personal name string into InvenioRDM format."""
    if not name_text or not name_text.strip():
        return None

    name_text = name_text.strip()

    # Parse "Last, First" format
    if ',' in name_text:
        parts = name_text.split(',', 1)
        family_name = parts[0].strip()
        given_name = parts[1].strip() if len(parts) > 1 else ""
    else:
        # Assume single name or "First Last" format
        parts = name_text.split()
        if len(parts) > 1:
            given_name = " ".join(parts[:-1])
            family_name = parts[-1]
        elif len(parts) == 1:
            # Single name - use as family name
            family_name = parts[0]
            given_name = ""
        else:
            # Fallback for empty or problematic names
            family_name = name_text.strip() if name_text.strip() else "Unknown"
            given_name = ""

    # Ensure family_name is never empty after processing
    if not family_name or not family_name.strip():
        family_name = name_text.strip() if name_text.strip() else "Unknown"

    person_data = {
        "type": "personal",
        "name": name_text
    }

    # Only add family_name and given_name if they're not empty
    family_name_clean = family_name.strip() if family_name else ""
    given_name_clean = given_name.strip() if given_name else ""

    if family_name_clean:
        person_data["family_name"] = family_name_clean
    if given_name_clean:
        person_data["given_name"] = given_name_clean

    return {"person_or_org": person_data}


def parse_personal_name(name_field) -> Dict[str, Any]:
    """Parse MARC personal name field (100/700) into InvenioRDM format."""
    subfield_a = name_field.find('.//marc:subfield[@code="a"]', MARC_NS)
    subfield_q = name_field.find('.//marc:subfield[@code="q"]', MARC_NS)
    subfield_u = name_field.find('.//marc:subfield[@code="u"]', MARC_NS)

    if subfield_a is None:
        return None

    name_text = subfield_a.text.strip()

    # Add fuller form of name if present
    if subfield_q is not None:
        name_text = f"{name_text} {subfield_q.text.strip()}".strip()

    # Use the shared parsing function
    result = parse_personal_name_from_text(name_text)
    if result is None:
        return None

    # Add affiliation if present
    if subfield_u is not None:
        result["affiliations"] = [{"name": subfield_u.text.strip()}]

    return result


def parse_corporate_name(name_field) -> Dict[str, Any]:
    """Parse MARC corporate name field (110/710) into InvenioRDM format."""
    subfield_a = name_field.find('.//marc:subfield[@code="a"]', MARC_NS)

    if subfield_a is None:
        return None

    return {
        "person_or_org": {
            "type": "organizational",
            "name": subfield_a.text.strip()
        }
    }


def extract_full_date(date_text: str) -> Optional[str]:
    """Extract date in YYYY, YYYY-MM, or YYYY-MM-DD format from date string."""
    if not date_text:
        return None

    # Clean up the date text
    date_text = date_text.strip()

    # Try to match various date formats
    # YYYY-MM-DD format
    match = re.search(r'(19|20)\d{2}-\d{2}-\d{2}', date_text)
    if match:
        return match.group()

    # YYYY/MM/DD format
    match = re.search(r'(19|20)\d{2}/\d{2}/\d{2}', date_text)
    if match:
        date_parts = match.group().split('/')
        return f"{date_parts[0]}-{date_parts[1]}-{date_parts[2]}"

    # YYYY-MM format
    match = re.search(r'(19|20)\d{2}-\d{2}', date_text)
    if match:
        return match.group()

    # YYYY/MM format
    match = re.search(r'(19|20)\d{2}/\d{2}', date_text)
    if match:
        date_parts = match.group().split('/')
        return f"{date_parts[0]}-{date_parts[1]}"

    # Month YYYY format (e.g., "June 2020")
    month_names = {
        'january': '01', 'february': '02', 'march': '03', 'april': '04',
        'may': '05', 'june': '06', 'july': '07', 'august': '08',
        'september': '09', 'october': '10', 'november': '11', 'december': '12',
        'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04',
        'may': '05', 'jun': '06', 'jul': '07', 'aug': '08',
        'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12'
    }

    for month_name, month_num in month_names.items():
        pattern = rf'{month_name}\s+(19|20)\d{{2}}'
        match = re.search(pattern, date_text.lower())
        if match:
            year = re.search(r'(19|20)\d{2}', match.group()).group()
            return f"{year}-{month_num}"

    # Just YYYY format (fallback)
    year_match = re.search(r'(19|20)\d{2}', date_text)
    if year_match:
        return year_match.group()

    logger.warning(f"Could not extract date from: '{date_text}'")
    return None


def scrape_doi_publication_date(doi: str) -> Optional[str]:
    """Scrape publication date from DOI URL.

    Args:
        doi: DOI identifier

    Returns:
        Publication date in YYYY-MM-DD format, or None if not found
    """
    try:
        # Construct DOI URL
        if doi.startswith('http'):
            url = doi
        elif doi.startswith('10.'):
            url = f'https://doi.org/{doi}'
        else:
            return None

        # Make request with timeout
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        response.raise_for_status()

        # Look for Physical Review publication date pattern
        html = response.text

        # Pattern: <strong>Published 13 May, 2016</strong>
        pub_date_match = re.search(r'<strong>Published\s+(\d{1,2})\s+(\w+),?\s+(\d{4})</strong>', html, re.IGNORECASE)
        if pub_date_match:
            day, month_name, year = pub_date_match.groups()

            # Convert month name to number
            month_map = {
                'january': 1, 'february': 2, 'march': 3, 'april': 4,
                'may': 5, 'june': 6, 'july': 7, 'august': 8,
                'september': 9, 'october': 10, 'november': 11, 'december': 12,
                'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
                'may': 5, 'jun': 6, 'jul': 7, 'aug': 8,
                'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
            }

            month_num = month_map.get(month_name.lower())
            if month_num:
                # Return in YYYY-MM-DD format
                return f"{year}-{month_num:02d}-{int(day):02d}"

        # Alternative pattern: look for other date formats in Physical Review pages
        # You can add more patterns here as needed

        return None

    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to fetch DOI {doi}: {e}")
        return None
    except Exception as e:
        logger.warning(f"Error scraping DOI {doi}: {e}")
        return None


def determine_resource_type(record_elem) -> Dict[str, str]:
    """Determine resource type from MARC record."""
    # Check MARC 983 (Local resource type - highest priority for this collection)
    local_type_field = record_elem.find('.//marc:datafield[@tag="983"]', MARC_NS)
    if local_type_field is not None:
        type_a = local_type_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if type_a is not None:
            type_text = type_a.text.strip().lower()
            for key, value in RESOURCE_TYPE_MAPPINGS.items():
                if key in type_text:
                    return {'id': value}

    ''''# Check MARC 037 (Submission form ID - maps to resource type)
    submission_form = record_elem.find('.//marc:datafield[@tag="037"]', MARC_NS)
    if submission_form is not None:
        form_a = submission_form.find('.//marc:subfield[@code="a"]', MARC_NS)
        form_b = submission_form.find('.//marc:subfield[@code="b"]', MARC_NS)

        for subfield in [form_a, form_b]:
            if subfield is not None:
                form_text = subfield.text.strip().lower()
                for key, value in RESOURCE_TYPE_MAPPINGS.items():
                    if key in form_text:
                        return {'id': value}'''

    # Check MARC 336 (Content Type)
    content_type_field = record_elem.find('.//marc:datafield[@tag="336"]', MARC_NS)
    if content_type_field is not None:
        content_type_a = content_type_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if content_type_a is not None:
            content_type = content_type_a.text.strip().lower()
            for key, value in RESOURCE_TYPE_MAPPINGS.items():
                if key in content_type:
                    return {'id': value}

    '''# Check MARC 502 (Dissertation Note)
    dissertation_field = record_elem.find('.//marc:datafield[@tag="502"]', MARC_NS)
    if dissertation_field is not None:
        return {'id': 'publication-thesis'}

    # Check MARC 655 (Genre/Form)
    genre_fields = record_elem.findall('.//marc:datafield[@tag="655"]', MARC_NS)
    for genre_field in genre_fields:
        genre_a = genre_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if genre_a is not None:
            genre_text = genre_a.text.strip().lower()
            for key, value in RESOURCE_TYPE_MAPPINGS.items():
                if key in genre_text:
                    return {'id': value}'''

    # Default to article
    return {'id': 'other'}


def extract_ror_id_from_identifier(identifier: str) -> Optional[str]:
    """Extract ROR ID from various identifier formats using idutils.

    Args:
        identifier: The identifier string to check

    Returns:
        ROR ID if valid, None otherwise
    """
    if not identifier:
        logger.debug("extract_ror_id_from_identifier: empty identifier")
        return None

    identifier = identifier.strip()
    logger.debug(f"extract_ror_id_from_identifier: processing '{identifier}'")

    # Check if it's a ROR URL and extract the ID first
    if idutils.is_url(identifier) and 'ror.org/' in identifier.lower():
        logger.debug(f"extract_ror_id_from_identifier: ROR URL detected '{identifier}'")
        # Extract the ROR ID from the URL
        ror_match = re.search(r'ror\.org/([0-9a-z]+)', identifier.lower())
        if ror_match:
            extracted_id = ror_match.group(1)
            logger.debug(f"extract_ror_id_from_identifier: extracted '{extracted_id}'")
            # Validate the extracted ID
            if idutils.is_ror(extracted_id):
                logger.debug(f"extract_ror_id_from_identifier: valid ROR ID '{extracted_id}'")
                return extracted_id
            else:
                logger.debug(f"extract_ror_id_from_identifier: invalid ROR ID '{extracted_id}'")

    # Check if it's already a plain ROR ID (not a URL)
    elif idutils.is_ror(identifier) and not idutils.is_url(identifier):
        logger.debug(f"extract_ror_id_from_identifier: direct ROR ID '{identifier}'")
        return identifier

    logger.debug(f"extract_ror_id_from_identifier: no valid ROR ID found in '{identifier}'")
    return None


def parse_marc_record(record_elem) -> Dict[str, Any]:
    """Convert MARCXML record to InvenioRDM format.

    Args:
        record_elem: XML element containing a MARC record

    Returns:
        Dictionary with InvenioRDM record data
    """
    metadata = {}

    # ==================== RESOURCE TYPE ====================

    resource_type = determine_resource_type(record_elem)
    metadata['resource_type'] = resource_type

    # ==================== CREATORS AND CONTRIBUTORS ====================

    creators = []
    contributors = []
    creator_sources = []  # Track which MARC fields provided creators

    # Extract additional personal contributors (MARC 700)
    added_personal = record_elem.findall('.//marc:datafield[@tag="700"]', MARC_NS)
    for personal_field in added_personal:
        contributor_data = parse_personal_name(personal_field)
        if contributor_data:
            # Add ORCID if present
            contrib_orcid = personal_field.find('.//marc:subfield[@code="1"]', MARC_NS)
            if contrib_orcid is not None:
                orcid_id = contrib_orcid.text.strip()
                if 'orcid.org' in orcid_id:
                    orcid_id = orcid_id.split('/')[-1]  # Extract just the ID
                # Validate ORCID format (should be XXXX-XXXX-XXXX-XXXX)
                if len(orcid_id) == 19 and orcid_id.count('-') == 3:
                    contributor_data["person_or_org"]["identifiers"] = [{
                        "identifier": orcid_id,
                        "scheme": "orcid"
                    }]

            # Determine role from subfield $e or $4
            role_e = personal_field.find('.//marc:subfield[@code="e"]', MARC_NS)
            role_4 = personal_field.find('.//marc:subfield[@code="4"]', MARC_NS)

            role = None
            if role_e is not None:
                role_text = role_e.text.strip().lower()
                role = CONTRIBUTOR_ROLE_MAPPINGS.get(role_text, 'contributor')
            elif role_4 is not None:
                role = role_4.text.strip()

            if role:
                contributor_data['role'] = {'id': role}

            contributors.append(contributor_data)

    # Extract additional corporate contributors (MARC 710)
    added_corporate = record_elem.findall('.//marc:datafield[@tag="710"]', MARC_NS)
    for corporate_field in added_corporate:
        contributor_data = parse_corporate_name(corporate_field)
        if contributor_data:
            contributors.append(contributor_data)

    # Extract additional contributors from local/variant fields (MARC 701-713)
    for tag in ['701', '702', '703', '711', '712', '713']:
        variant_fields = record_elem.findall(f'.//marc:datafield[@tag="{tag}"]', MARC_NS)
        for field in variant_fields:
            if tag in ['701', '702', '703']:  # Personal name variants
                contributor_data = parse_personal_name(field)
            else:  # Corporate name variants
                contributor_data = parse_corporate_name(field)

            if contributor_data:
                contributors.append(contributor_data)

    # Extract contributors from MARC 720 (Uncontrolled names)
    contributor_720_fields = record_elem.findall('.//marc:datafield[@tag="720"]', MARC_NS)
    for contrib_field in contributor_720_fields:
        contrib_name = contrib_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        contrib_role = contrib_field.find('.//marc:subfield[@code="e"]', MARC_NS)
        contrib_affiliation = contrib_field.find('.//marc:subfield[@code="u"]', MARC_NS)
        contrib_orcid = contrib_field.find('.//marc:subfield[@code="1"]', MARC_NS)

        if contrib_name is not None:
            # Determine if personal or organizational
            name_text = contrib_name.text.strip()

            # Check for role-specific handling
            role = 'contributor'  # default
            if contrib_role is not None:
                role_text = contrib_role.text.strip().lower()
                if role_text in CONTRIBUTOR_ROLE_MAPPINGS:
                    role = CONTRIBUTOR_ROLE_MAPPINGS[role_text]
                elif role_text in ['advisor', 'supervisor']:
                    role = 'supervisor'
                elif role_text == 'sponsor':
                    role = 'sponsor'

            # Check for special roles based on indicators
            if contrib_field.get('ind1') == '1':
                if contrib_field.get('ind2') == '2':
                    role = 'supervisor'  # Advisor
                elif contrib_field.get('ind2') == '4':
                    role = 'other'  # Committee member

            # Use parse_personal_name for consistent name handling
            if any(word in name_text.lower() for word in ['university', 'institute', 'foundation', 'center']):
                # Organizational name
                contributor_data = {
                    "person_or_org": {
                        "type": "organizational",
                        "name": name_text
                    },
                    "role": {"id": role}
                }
            else:
                # Personal name - use the shared parsing function
                parsed_name = parse_personal_name_from_text(name_text)
                if parsed_name:
                    contributor_data = {
                        "person_or_org": parsed_name["person_or_org"],
                        "role": {"id": role}
                    }
                else:
                    # Fallback if parsing fails
                    contributor_data = {
                        "person_or_org": {
                            "type": "personal",
                            "name": name_text
                        },
                        "role": {"id": role}
                    }

            # Add ORCID if present
            if contrib_orcid is not None:
                orcid_id = contrib_orcid.text.strip()
                if 'orcid.org' in orcid_id:
                    orcid_id = orcid_id.split('/')[-1]  # Extract just the ID
                # Validate ORCID format (should be XXXX-XXXX-XXXX-XXXX)
                if len(orcid_id) == 19 and orcid_id.count('-') == 3:
                    contributor_data["person_or_org"]["identifiers"] = [{
                        "identifier": orcid_id,
                        "scheme": "orcid"
                    }]

            # Add affiliation if present
            if contrib_affiliation is not None:
                contributor_data["affiliations"] = [{"name": contrib_affiliation.text.strip()}]

            contributors.append(contributor_data)

    # Extract submitter information from MARC 270
    # Note: Email identifiers are not supported in Invenio, so we skip this
    # submitter_270 = record_elem.find('.//marc:datafield[@tag="270"]', MARC_NS)
    # if submitter_270 is not None:
    #     submitter_email = submitter_270.find('.//marc:subfield[@code="m"]', MARC_NS)
    #     if submitter_email is not None:
    #         # Email scheme not supported in Invenio RDM
    #         pass

    # Ensure we have at least one creator - promote all contributors if needed
    if not creators and contributors:
        # Move all contributors to creators, removing roles
        creators = []
        for contrib in contributors:
            creator = {
                "person_or_org": contrib["person_or_org"]
            }
            # Copy affiliations if present
            if "affiliations" in contrib:
                creator["affiliations"] = contrib["affiliations"]
            creators.append(creator)

        contributors = []
        # Check if any contributors came from 701-713 fields
        has_701_713 = any(record_elem.find(f'.//marc:datafield[@tag="{tag}"]', MARC_NS) is not None
                          for tag in ['701', '702', '703', '711', '712', '713'])
        if has_701_713:
            creator_sources.append("701-713 (promoted)")
        else:
            creator_sources.append("700/710 (promoted)")

    # If still no creators, try to extract from statement of responsibility (MARC 245$c)
    if not creators:
        title_field = record_elem.find('.//marc:datafield[@tag="245"]', MARC_NS)
        if title_field is not None:
            title_c = title_field.find('.//marc:subfield[@code="c"]', MARC_NS)
            if title_c is not None:
                creator_name = title_c.text.strip()
                # Clean up common statement of responsibility text
                creator_name = creator_name.replace('by ', '').replace('By ', '').strip()
                if creator_name:
                    creators = [{
                        "person_or_org": {
                            "type": "personal",
                            "name": creator_name
                        }
                    }]
                    creator_sources.append("245$c")

    # Final fallback - create unknown creator
    if not creators:
        creators = [{
            "person_or_org": {
                "type": "organizational",
                "name": "Unknown"
            }
        }]
        creator_sources.append("Unknown")

    if creators:
        metadata['creators'] = creators
    if contributors:
        metadata['contributors'] = contributors

    # ==================== TITLE ====================

    title_field = record_elem.find('.//marc:datafield[@tag="245"]', MARC_NS)
    if title_field is not None:
        title_a = title_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        title_b = title_field.find('.//marc:subfield[@code="b"]', MARC_NS)
        title_c = title_field.find('.//marc:subfield[@code="c"]', MARC_NS)

        title = title_a.text.strip() if title_a is not None else "Untitled"
        if title_b is not None:
            title += f": {title_b.text.strip()}"

        metadata['title'] = title
    else:
        metadata['title'] = "Untitled"

    # ==================== VERSION ====================

    version_field = record_elem.find('.//marc:datafield[@tag="251"]', MARC_NS)
    if version_field is not None:
        version_a = version_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if version_a is not None:
            metadata['version'] = version_a.text.strip()

    # ==================== IDENTIFIERS ====================

    identifiers = []

    # Control number (MARC 001)
    # control_001 = record_elem.find('.//marc:controlfield[@tag="001"]', MARC_NS)
    # if control_001 is not None:
    #    identifiers.append({
    #        'identifier': control_001.text.strip(),
    #        'scheme': 'marc_control_number'
    #    })

    # DOI and other identifiers (MARC 024)
    identifier_024_fields = record_elem.findall('.//marc:datafield[@tag="024"]', MARC_NS)
    for id_field in identifier_024_fields:
        subfield_a = id_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        subfield_d = id_field.find('.//marc:subfield[@code="d"]', MARC_NS)
        subfield_2 = id_field.find('.//marc:subfield[@code="2"]', MARC_NS)

        # Handle DOI identifiers (024$7$2="doi")
        if (id_field.get('ind1') == '7' and subfield_2 is not None and
                subfield_2.text.strip().lower() == 'doi' and subfield_a is not None):
            doi_value = subfield_a.text.strip()
            # Validate DOI using idutils
            if idutils.is_doi(doi_value):
                identifiers.append({
                    'identifier': doi_value,
                    'scheme': 'doi'
                })
            else:
                logger.error(f"Invalid DOI found: {doi_value}")

        # Handle other identifiers in $a and $d
        for subfield in [subfield_a, subfield_d]:
            if subfield is not None:
                id_value = subfield.text.strip()
                if id_value and not any(existing['identifier'] == id_value for existing in identifiers):
                    # Try to determine scheme from content
                    if idutils.is_doi(id_value):
                        identifiers.append({
                            'identifier': id_value,
                            'scheme': 'doi'
                        })
                    elif 'US ' in id_value and (' A' in id_value or ' B' in id_value):
                        # Patent number pattern
                        identifiers.append({
                            'identifier': id_value,
                            'scheme': 'other'
                        })
                    else:
                        identifiers.append({
                            'identifier': id_value,
                            'scheme': 'other'
                        })

    # ISBN (MARC 020)
    isbn_fields = record_elem.findall('.//marc:datafield[@tag="020"]', MARC_NS)
    for isbn_field in isbn_fields:
        isbn_a = isbn_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if isbn_a is not None:
            isbn_text = isbn_a.text.strip()
            # Clean ISBN (remove any extra text after space)
            isbn = isbn_text.split()[0] if isbn_text else ""
            if isbn:
                identifiers.append({
                    'identifier': isbn,
                    'scheme': 'isbn'
                })

    # ISSN (MARC 022)
    issn_fields = record_elem.findall('.//marc:datafield[@tag="022"]', MARC_NS)
    for issn_field in issn_fields:
        issn_a = issn_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if issn_a is not None:
            issn_value = issn_a.text.strip()
            # Validate ISSN using idutils
            if idutils.is_issn(issn_value):
                identifiers.append({
                    'identifier': issn_value,
                    'scheme': 'issn'
                })
            else:
                logger.error(f"Invalid ISSN found: {issn_value}")

    # Electronic location/URLs (MARC 856)
    url_fields = record_elem.findall('.//marc:datafield[@tag="856"]', MARC_NS)
    for url_field in url_fields:
        url_u = url_field.find('.//marc:subfield[@code="u"]', MARC_NS)
        if url_u is not None:
            url_text = url_u.text.strip()
            if url_text.startswith('http'):
                identifiers.append({
                    'identifier': url_text,
                    'scheme': 'url'
                })

    # Handle identifiers (MARC 902)
    '''handle_fields = record_elem.findall('.//marc:datafield[@tag="902"]', MARC_NS)
    for handle_field in handle_fields:
        handle_a = handle_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if handle_a is not None:
            handle_text = handle_a.text.strip()
            if 'handle.net' in handle_text or handle_text.startswith('hdl:'):
                identifiers.append({
                    'identifier': handle_text,
                    'scheme': 'handle'
                })'''

    # OAI identifiers (MARC 909CO)
    oai_fields = record_elem.findall('.//marc:datafield[@tag="909"][@ind1="C"][@ind2="O"]', MARC_NS)
    for oai_field in oai_fields:
        oai_o = oai_field.find('.//marc:subfield[@code="o"]', MARC_NS)
        if oai_o is not None:
            oai_text = oai_o.text.strip()
            if oai_text.startswith('oai:'):
                identifiers.append({
                    'identifier': oai_text,
                    'scheme': 'other'
                })

    if identifiers:
        metadata['identifiers'] = identifiers

    # ==================== PUBLISHER AND DATES ====================

    date_source = None  # Track where publication date comes from

    # Publication info (MARC 260 or 264)
    pub_field_264 = record_elem.find('.//marc:datafield[@tag="264"]', MARC_NS)  # Preferred

    # Try 264 first
    if pub_field_264 is not None:
        # Publisher name
        pub_b = pub_field_264.find('.//marc:subfield[@code="b"]', MARC_NS)
        if pub_b is not None:
            metadata['publisher'] = pub_b.text.strip()

        # Publication date
        pub_c = pub_field_264.find('.//marc:subfield[@code="c"]', MARC_NS)
        if pub_c is not None:
            date = extract_full_date(pub_c.text.strip())
            if date:
                metadata['publication_date'] = date
                date_source = '264$c'

    # If no 264, try all 260 fields
    if 'publication_date' not in metadata:
        pub_fields_260 = record_elem.findall('.//marc:datafield[@tag="260"]', MARC_NS)
        for pub_field_260 in pub_fields_260:
            # Publisher name (from first field that has it)
            if 'publisher' not in metadata:
                pub_b = pub_field_260.find('.//marc:subfield[@code="b"]', MARC_NS)
                if pub_b is not None:
                    metadata['publisher'] = pub_b.text.strip()

            # Publication date - prioritize $c over other subfields
            pub_c = pub_field_260.find('.//marc:subfield[@code="c"]', MARC_NS)
            if pub_c is not None:
                date = extract_full_date(pub_c.text.strip())
                if date:
                    metadata['publication_date'] = date
                    date_source = '260$c'
                    break  # Stop after finding first valid $c date

        # Try manufacture date (260$g) if no publication date found
        if 'publication_date' not in metadata:
            for pub_field_260 in pub_fields_260:
                pub_g = pub_field_260.find('.//marc:subfield[@code="g"]', MARC_NS)
                if pub_g is not None:
                    date = extract_full_date(pub_g.text.strip())
                    if date:
                        metadata['publication_date'] = date
                        date_source = '260$g (manufacture)'
                        break

    # Additional date information (MARC 269)
    if 'publication_date' not in metadata:
        date_269 = record_elem.find('.//marc:datafield[@tag="269"]', MARC_NS)
        if date_269 is not None:
            date_a = date_269.find('.//marc:subfield[@code="a"]', MARC_NS)
            if date_a is not None:
                date = extract_full_date(date_a.text.strip())
                if date:
                    metadata['publication_date'] = date
                    date_source = '269$a'

    # Additional fallback date sources
    if 'publication_date' not in metadata:
        # Try MARC 008 positions 7-10 (Date 1) and 11-14 (Date 2)
        control_008 = record_elem.find('.//marc:controlfield[@tag="008"]', MARC_NS)
        if control_008 is not None and len(control_008.text) >= 14:
            date1 = control_008.text[7:11]  # Positions 7-10
            date2 = control_008.text[11:15]  # Positions 11-14

            # Use Date 1 if it's a valid 4-digit year
            if date1.isdigit() and 1000 <= int(date1) <= 2100:
                metadata['publication_date'] = date1
                date_source = '008 (positions 7-14)'
            # Otherwise try Date 2
            elif date2.isdigit() and 1000 <= int(date2) <= 2100:
                metadata['publication_date'] = date2
                date_source = '008 (positions 7-14)'

        # Try copyright date (MARC 264 ind2="4")
        if 'publication_date' not in metadata:
            copyright_field = record_elem.find('.//marc:datafield[@tag="264"][@ind2="4"]', MARC_NS)
            if copyright_field is not None:
                copyright_c = copyright_field.find('.//marc:subfield[@code="c"]', MARC_NS)
                if copyright_c is not None:
                    date = extract_full_date(copyright_c.text.strip())
                    if date:
                        metadata['publication_date'] = date
                        date_source = '264$c (copyright)'

        # Try creation date (MARC 046)
        if 'publication_date' not in metadata:
            creation_field = record_elem.find('.//marc:datafield[@tag="046"]', MARC_NS)
            if creation_field is not None:
                creation_k = creation_field.find('.//marc:subfield[@code="k"]', MARC_NS)  # Beginning date
                if creation_k is not None:
                    date = extract_full_date(creation_k.text.strip())
                    if date:
                        metadata['publication_date'] = date
                        date_source = '046$k'

        # Try to extract publication date from DOI scraping (Physical Review journals)
        if 'publication_date' not in metadata and 'identifiers' in metadata:
            for identifier in metadata['identifiers']:
                if identifier.get('scheme') == 'doi':
                    doi = identifier['identifier']

                    # Try scraping for Physical Review DOIs
                    if '10.1103/PhysRev' in doi:
                        scraped_date = scrape_doi_publication_date(doi)
                        if scraped_date:
                            metadata['publication_date'] = scraped_date
                            date_source = 'DOI scraping (Physical Review)'
                            break

                    # Fallback: Physical Review D volume mapping if scraping fails
                    phys_rev_d_match = re.search(r'10\.1103/PhysRevD\.(\d+)\.', doi)
                    if phys_rev_d_match:
                        volume = int(phys_rev_d_match.group(1))
                        # PhysRevD volume to year mapping (approximate)
                        if volume >= 85:  # Starting from known volume/year
                            year = str(2012 + (volume - 85) // 2)  # ~2 volumes per year
                            metadata['publication_date'] = year
                            date_source = f'DOI volume mapping (PhysRevD vol.{volume})'
                            break

                    # Other Physical Review journals could be added here
                    # PhysRevLett, PhysRevX, etc.

    # ==================== LANGUAGE ====================

    lang_field = record_elem.find('.//marc:datafield[@tag="041"]', MARC_NS)
    if lang_field is not None:
        lang_a = lang_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if lang_a is not None:
            lang_code = lang_a.text.strip().lower()
            if lang_code and len(lang_code) >= 2:
                # Convert 2-digit codes to 3-digit codes
                if len(lang_code) == 2 and lang_code in LANGUAGE_MAPPINGS:
                    lang_code = LANGUAGE_MAPPINGS[lang_code]
                elif len(lang_code) == 3:
                    # Already 3-digit, use as-is
                    pass
                else:
                    logger.warning(f"Unknown language code: {lang_code}")
                    lang_code = None

                if lang_code:
                    metadata['languages'] = [{'id': lang_code}]
            else:
                logger.warning(f"Invalid language code: {lang_code}")

    # ==================== SUBJECTS ====================

    subjects = []

    # Subject headings (MARC 650)
    subject_650_fields = record_elem.findall('.//marc:datafield[@tag="650"]', MARC_NS)
    for subject_field in subject_650_fields:
        subfield_a = subject_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if subfield_a is not None:
            subjects.append({'subject': subfield_a.text.strip()})

    # Uncontrolled terms (MARC 653)
    subject_653_fields = record_elem.findall('.//marc:datafield[@tag="653"]', MARC_NS)
    for subject_field in subject_653_fields:
        subfield_a = subject_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if subfield_a is not None:
            subjects.append({'subject': subfield_a.text.strip()})

    # Local subject headings (MARC 690-699)
    for tag in ['690', '691', '692', '693', '694', '695', '696', '697', '698', '699']:
        local_subject_fields = record_elem.findall(f'.//marc:datafield[@tag="{tag}"]', MARC_NS)
        for subject_field in local_subject_fields:
            subfield_a = subject_field.find('.//marc:subfield[@code="a"]', MARC_NS)
            if subfield_a is not None:
                subjects.append({'subject': subfield_a.text.strip()})

    if subjects:
        metadata['subjects'] = subjects

    # ==================== DESCRIPTION/ABSTRACT ====================

    desc_field = record_elem.find('.//marc:datafield[@tag="520"]', MARC_NS)
    if desc_field is not None:
        desc_a = desc_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if desc_a is not None:
            desc_text = desc_a.text.strip()
            # Ignore "No abstract" values
            if desc_text.lower() != "no abstract":
                metadata['description'] = desc_text

    # ==================== ADDITIONAL DESCRIPTIONS ====================

    additional_descriptions = []
    record_additional_description_sources = []  # Track sources for this record

    # Alternative descriptions from MARC 520$b (alternative language)
    desc_520_fields = record_elem.findall('.//marc:datafield[@tag="520"]', MARC_NS)
    for desc_field in desc_520_fields:
        desc_b = desc_field.find('.//marc:subfield[@code="b"]', MARC_NS)
        if desc_b is not None:
            additional_descriptions.append({
                'description': desc_b.text.strip(),
                'type': {'id': 'other', 'title': {'en': 'Alternative Description'}}
            })
            record_additional_description_sources.append('520$b')

    # General notes (MARC 500)
    general_note_fields = record_elem.findall('.//marc:datafield[@tag="500"]', MARC_NS)
    for note_field in general_note_fields:
        note_a = note_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if note_a is not None:
            additional_descriptions.append({
                'description': note_a.text.strip(),
                'type': {'id': 'other'}
            })
            record_additional_description_sources.append('500')

    # Local notes (MARC 590)
    local_note_fields = record_elem.findall('.//marc:datafield[@tag="590"]', MARC_NS)
    for note_field in local_note_fields:
        note_a = note_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if note_a is not None:
            additional_descriptions.append({
                'description': note_a.text.strip(),
                'type': {'id': 'other'}
            })
            record_additional_description_sources.append('590')

    # Additional local notes (MARC 591) - often acknowledgements
    acknowledgement_fields = record_elem.findall('.//marc:datafield[@tag="591"]', MARC_NS)
    for note_field in acknowledgement_fields:
        note_a = note_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if note_a is not None:
            additional_descriptions.append({
                'description': note_a.text.strip(),
                'type': {'id': 'other', 'title': {'en': 'Acknowledgements'}}
            })
            record_additional_description_sources.append('591')

    # Administrative notes (MARC 592) - internal use only, skip
    # Notes (MARC 593)
    note_593_fields = record_elem.findall('.//marc:datafield[@tag="593"]', MARC_NS)
    for note_field in note_593_fields:
        note_a = note_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if note_a is not None:
            additional_descriptions.append({
                'description': note_a.text.strip(),
                'type': {'id': 'other', 'title': {'en': 'Notes'}}
            })
            record_additional_description_sources.append('593')

    # Additional local notes (MARC 594)
    note_594_fields = record_elem.findall('.//marc:datafield[@tag="594"]', MARC_NS)
    for note_field in note_594_fields:
        note_a = note_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if note_a is not None:
            additional_descriptions.append({
                'description': note_a.text.strip(),
                'type': {'id': 'other'}
            })
            record_additional_description_sources.append('594')

    # ==================== RIGHTS INFORMATION ====================

    rights = []

    # Copyright status (MARC 542) - preferred field for rights
    rights_542 = record_elem.find('.//marc:datafield[@tag="542"]', MARC_NS)
    if rights_542 is not None:
        # Check various subfields for rights information
        rights_f = rights_542.find('.//marc:subfield[@code="f"]', MARC_NS)  # Copyright statement
        rights_l = rights_542.find('.//marc:subfield[@code="l"]', MARC_NS)  # Copyright status
        rights_n = rights_542.find('.//marc:subfield[@code="n"]', MARC_NS)  # Note

        if rights_f is not None:
            rights_text = rights_f.text.strip()
            # Check if it's a Creative Commons license
            if rights_text.upper().startswith('CC '):
                # Try to map to proper license ID
                license_key = rights_text.lower()
                if license_key in LICENSE_MAPPINGS:
                    rights.append({
                        'id': LICENSE_MAPPINGS[license_key],
                        'title': {'en': rights_text}
                    })
                else:
                    # Fallback to generic rights statement
                    rights.append({'title': {'en': rights_text}})
            else:
                rights.append({'title': {'en': rights_text}})
        elif rights_l is not None:
            rights.append({'title': {'en': rights_l.text.strip()}})
        elif rights_n is not None:
            rights.append({'title': {'en': rights_n.text.strip()}})

    # Fallback: Terms governing use (MARC 540)
    if not rights:
        rights_540 = record_elem.find('.//marc:datafield[@tag="540"]', MARC_NS)
        if rights_540 is not None:
            rights_a = rights_540.find('.//marc:subfield[@code="a"]', MARC_NS)
            if rights_a is not None:
                rights.append({'title': {'en': rights_a.text.strip()}})

    # Distribution license (MARC 908)
    distribution_license = record_elem.find('.//marc:datafield[@tag="908"]', MARC_NS)
    if distribution_license is not None:
        license_a = distribution_license.find('.//marc:subfield[@code="a"]', MARC_NS)
        if license_a is not None:
            license_text = license_a.text.strip()
            if license_text and license_text.lower() != 'i agree':
                rights.append({'title': {'en': f"Distribution License: {license_text}"}})

    if rights:
        metadata['rights'] = rights

    # ==================== RELATED IDENTIFIERS ====================

    related_identifiers = []

    # Host item entry (MARC 773) - for articles in journals/books
    host_773 = record_elem.find('.//marc:datafield[@tag="773"]', MARC_NS)
    if host_773 is not None:
        # Look for ISBN/ISSN in host item first (more reliable identifiers)
        host_isbn = host_773.find('.//marc:subfield[@code="z"]', MARC_NS)  # ISBN
        host_issn = host_773.find('.//marc:subfield[@code="x"]', MARC_NS)  # ISSN

        if host_isbn is not None:
            related_identifiers.append({
                'identifier': host_isbn.text.strip(),
                'scheme': 'isbn',
                'relation_type': {'id': 'ispartof'}
            })
        elif host_issn is not None:
            related_identifiers.append({
                'identifier': host_issn.text.strip(),
                'scheme': 'issn',
                'relation_type': {'id': 'ispartof'}
            })
        # Skip title-only entries as 'title' is not a valid scheme

    # Related identifiers (MARC 789)
    related_789_fields = record_elem.findall('.//marc:datafield[@tag="789"]', MARC_NS)
    for rel_field in related_789_fields:
        rel_identifier = rel_field.find('.//marc:subfield[@code="w"]', MARC_NS)
        rel_type = rel_field.find('.//marc:subfield[@code="e"]', MARC_NS)

        if rel_identifier is not None:
            identifier_text = rel_identifier.text.strip()
            relation_type = 'cites'  # default

            if rel_type is not None:
                relation_text = rel_type.text.strip().lower()
                # Map common relation types
                if 'cited by' in relation_text:
                    relation_type = 'iscitedby'
                elif 'cites' in relation_text:
                    relation_type = 'cites'
                elif 'part of' in relation_text:
                    relation_type = 'ispartof'
                elif 'supplement' in relation_text:
                    relation_type = 'issupplementto'

            # Determine scheme based on identifier format
            scheme = 'url'  # default
            if identifier_text.startswith('10.'):
                scheme = 'doi'
            elif 'orcid.org' in identifier_text:
                scheme = 'orcid'
            elif 'handle.net' in identifier_text or identifier_text.startswith('hdl:'):
                scheme = 'handle'

            related_identifiers.append({
                'identifier': identifier_text,
                'scheme': scheme,
                'relation_type': {'id': relation_type}
            })

    # Related resources (MARC 856 with specific indicators)
    related_856_fields = record_elem.findall('.//marc:datafield[@tag="856"][@ind1="4"][@ind2="0"]', MARC_NS)
    for rel_field in related_856_fields:
        rel_url = rel_field.find('.//marc:subfield[@code="u"]', MARC_NS)
        rel_desc = rel_field.find('.//marc:subfield[@code="y"]', MARC_NS)

        if rel_url is not None:
            url_text = rel_url.text.strip()
            relation_type = 'references'  # default

            if rel_desc is not None:
                desc_text = rel_desc.text.strip().lower()
                if 'article' in desc_text:
                    relation_type = 'issupplementto'
                elif 'replication' in desc_text or 'data' in desc_text:
                    relation_type = 'issupplementedby'

            related_identifiers.append({
                'identifier': url_text,
                'scheme': 'url',
                'relation_type': {'id': relation_type}
            })

    # Archive locations (MARC 857)
    archive_857_fields = record_elem.findall('.//marc:datafield[@tag="857"][@ind1="4"][@ind2="0"]', MARC_NS)
    for archive_field in archive_857_fields:
        archive_url = archive_field.find('.//marc:subfield[@code="u"]', MARC_NS)
        archive_desc = archive_field.find('.//marc:subfield[@code="y"]', MARC_NS)

        if archive_url is not None:
            url_text = archive_url.text.strip()

            # Check if it's a DOI
            scheme = 'url'
            if 'doi.org' in url_text or url_text.startswith('10.'):
                scheme = 'doi'
                # Extract DOI from URL if needed
                if 'doi.org/' in url_text:
                    url_text = url_text.split('doi.org/')[-1]

            related_identifiers.append({
                'identifier': url_text,
                'scheme': scheme,
                'relation_type': {'id': 'issupplementedby'}
            })

    if related_identifiers:
        metadata['related_identifiers'] = related_identifiers

    # ==================== SIZES (PHYSICAL DESCRIPTION) ====================

    # Extract page count or other physical details (MARC 300)
    sizes = []
    phys_300_fields = record_elem.findall('.//marc:datafield[@tag="300"]', MARC_NS)
    for phys_300 in phys_300_fields:
        phys_a = phys_300.find('.//marc:subfield[@code="a"]', MARC_NS)
        if phys_a is not None:
            phys_text = phys_a.text.strip()
            if phys_text:
                sizes.append(phys_text)

    if sizes:
        metadata['sizes'] = sizes

    # Add additional descriptions to metadata if any exist
    if additional_descriptions:
        metadata['additional_descriptions'] = additional_descriptions

    # ==================== LOCAL COLLECTION INFO (900 series) ====================

    # Publication status (MARC 981)
    # pub_status_981 = record_elem.find('.//marc:datafield[@tag="981"]', MARC_NS)
    # if pub_status_981 is not None:
    #    status_a = pub_status_981.find('.//marc:subfield[@code="a"]', MARC_NS)
    #    if status_a is not None:
    #        status_text = status_a.text.strip()
    #        # Add as custom metadata
    #        if 'custom' not in metadata:
    #            metadata['custom'] = {}
    #        metadata['custom']['publication_status'] = status_text

    # Collection/Set information (MARC 909CO $p)
    collection_909 = record_elem.findall('.//marc:datafield[@tag="909"][@ind1="C"][@ind2="O"]', MARC_NS)
    collections = []
    for coll_field in collection_909:
        coll_p = coll_field.find('.//marc:subfield[@code="p"]', MARC_NS)
        if coll_p is not None:
            coll_text = coll_p.text.strip()
            if coll_text and coll_text != 'GLOBAL_SET':
                collections.append(coll_text)

    # if collections:
    #    if 'custom' not in metadata:
    #        metadata['custom'] = {}
    #    metadata['custom']['collections'] = collections

    # ==================== CUSTOM FIELDS ====================

    custom_fields = {}

    # Thesis information (MARC 502)
    thesis_field = record_elem.find('.//marc:datafield[@tag="502"]', MARC_NS)
    if thesis_field is not None:
        thesis_type = thesis_field.find('.//marc:subfield[@code="b"]', MARC_NS)
        if thesis_type is not None:
            custom_fields['thesis:thesis'] = {
                'type': thesis_type.text.strip()
            }

    # Funding information (MARC 536) - only include funders with valid ROR IDs
    funding_fields = record_elem.findall('.//marc:datafield[@tag="536"]', MARC_NS)
    funding_list = []
    for funding_field in funding_fields:
        funding_info = {}

        # First check if there's a valid ROR ID in the funder identifier (536$q)
        funder_id_field = funding_field.find('.//marc:subfield[@code="q"]', MARC_NS)
        ror_id = None
        if funder_id_field is not None:
            original_id = funder_id_field.text.strip()
            ror_id = extract_ror_id_from_identifier(original_id)
            logger.debug(f"Funder ID processing: '{original_id}' -> '{ror_id}'")

        # Only process this funding entry if it has a valid ROR ID
        if ror_id is not None:
            # Award number
            award_number = funding_field.find('.//marc:subfield[@code="1"]', MARC_NS)
            if award_number is not None:
                funding_info['award'] = {'number': award_number.text.strip()}

            # Award title
            award_title = funding_field.find('.//marc:subfield[@code="a"]', MARC_NS)
            if award_title is not None:
                if 'award' not in funding_info:
                    funding_info['award'] = {}
                funding_info['award']['title'] = {'en': award_title.text.strip()}

            # Award identifier (536$c)
            award_id = funding_field.find('.//marc:subfield[@code="c"]', MARC_NS)
            if award_id is not None:
                if 'award' not in funding_info:
                    funding_info['award'] = {}
                funding_info['award']['id'] = award_id.text.strip()

            # Funder name
            funder_name = funding_field.find('.//marc:subfield[@code="o"]', MARC_NS)
            if funder_name is not None:
                funding_info['funder'] = {'name': funder_name.text.strip()}

            # Funder identifier - use the validated ROR ID in proper format
            funding_info['funder'] = funding_info.get('funder', {})
            funding_info['funder']['id'] = ror_id
            logger.debug(f"Setting funder ID to: '{ror_id}'")

            if funding_info:
                funding_list.append(funding_info)

    if funding_list:
        metadata['funding'] = funding_list

    # Meeting/Conference information (MARC 711)
    meeting_field = record_elem.find('.//marc:datafield[@tag="711"]', MARC_NS)
    if meeting_field is not None:
        meeting_info = {}

        # Meeting title
        meeting_title = meeting_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if meeting_title is not None:
            meeting_info['title'] = meeting_title.text.strip()

        # Meeting place
        meeting_place = meeting_field.find('.//marc:subfield[@code="c"]', MARC_NS)
        if meeting_place is not None:
            meeting_info['place'] = meeting_place.text.strip()

        if meeting_info:
            custom_fields['meeting'] = meeting_info

    # Journal information (MARC 773)
    journal_field = record_elem.find('.//marc:datafield[@tag="773"]', MARC_NS)
    if journal_field is not None:
        journal_info = {}

        # Journal title (try both $a and $t)
        journal_title_a = journal_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        journal_title_t = journal_field.find('.//marc:subfield[@code="t"]', MARC_NS)

        if journal_title_a is not None:
            journal_info['title'] = journal_title_a.text.strip()
        elif journal_title_t is not None:
            journal_info['title'] = journal_title_t.text.strip()

        # Journal volume
        journal_volume = journal_field.find('.//marc:subfield[@code="j"]', MARC_NS)
        if journal_volume is not None:
            journal_info['volume'] = journal_volume.text.strip()

        # Journal issue
        journal_issue = journal_field.find('.//marc:subfield[@code="k"]', MARC_NS)
        if journal_issue is not None:
            journal_info['issue'] = journal_issue.text.strip()

        if journal_info:
            custom_fields['journal:journal'] = journal_info

    # ==================== LOCATIONS/GEOGRAPHIC DATA ====================

    locations = []

    # Geographic coverage from MARC 522
    geo_522_fields = record_elem.findall('.//marc:datafield[@tag="522"]', MARC_NS)
    for geo_field in geo_522_fields:
        place_a = geo_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if place_a is not None:
            locations.append({
                'features': [{
                    'place': place_a.text.strip()
                }]
            })

    # Geographic data from MARC 975 (coordinates)
    geo_975_fields = record_elem.findall('.//marc:datafield[@tag="975"]', MARC_NS)
    for geo_field in geo_975_fields:
        place_a = geo_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        coord_b = geo_field.find('.//marc:subfield[@code="b"]', MARC_NS)  # lat for point
        coord_c = geo_field.find('.//marc:subfield[@code="c"]', MARC_NS)  # lng for point
        coord_d = geo_field.find('.//marc:subfield[@code="d"]', MARC_NS)  # coord1 for polygon
        coord_e = geo_field.find('.//marc:subfield[@code="e"]', MARC_NS)  # coord2 for polygon
        coord_f = geo_field.find('.//marc:subfield[@code="f"]', MARC_NS)  # coord3 for polygon
        coord_g = geo_field.find('.//marc:subfield[@code="g"]', MARC_NS)  # coord4 for polygon

        feature = {}

        if place_a is not None:
            feature['place'] = place_a.text.strip()

        # Check if we have point coordinates (lat/lng)
        if coord_b is not None and coord_c is not None:
            try:
                lat = float(coord_b.text.strip())
                lng = float(coord_c.text.strip())
                feature['geometry'] = {
                    'type': 'Point',
                    'coordinates': [lng, lat]  # GeoJSON format: [longitude, latitude]
                }
            except ValueError:
                logger.warning(f"Invalid coordinates in MARC 975: lat={coord_b.text}, lng={coord_c.text}")

        # Check if we have polygon coordinates (bounding box)
        elif all(coord is not None for coord in [coord_d, coord_e, coord_f, coord_g]):
            try:
                coord1 = float(coord_d.text.strip())
                coord2 = float(coord_e.text.strip())
                coord3 = float(coord_f.text.strip())
                coord4 = float(coord_g.text.strip())

                # Assuming these are bounding box coordinates: [west, east, north, south]
                feature['geometry'] = {
                    'type': 'Polygon',
                    'coordinates': [[
                        [coord1, coord4],  # southwest
                        [coord2, coord4],  # southeast
                        [coord2, coord3],  # northeast
                        [coord1, coord3],  # northwest
                        [coord1, coord4]  # close polygon
                    ]]
                }
            except ValueError:
                logger.warning(f"Invalid polygon coordinates in MARC 975")

        if feature:
            locations.append({'features': [feature]})

    if locations:
        metadata['locations'] = locations

    # Log creator sources for this record
    record_doi = "No DOI"
    if 'identifiers' in metadata:
        for identifier in metadata['identifiers']:
            if identifier.get('scheme') == 'doi':
                record_doi = identifier['identifier']
                break

    # Update global counters for creator sources
    for source in creator_sources:
        if source in creator_source_counts:
            creator_source_counts[source] += 1

    # Update global counters for date sources
    if date_source:
        # Handle DOI-related sources
        if 'DOI scraping' in date_source:
            date_source_counts['DOI scraping'] += 1
        elif 'DOI volume mapping' in date_source:
            date_source_counts['DOI volume mapping'] += 1
        elif date_source in date_source_counts:
            date_source_counts[date_source] += 1
    else:
        date_source_counts['missing'] += 1

    # Update global counters for additional description sources
    for source in record_additional_description_sources:
        if source in additional_description_source_counts:
            additional_description_source_counts[source] += 1

    # Check if record has additional descriptions but no main description
    global records_with_additional_but_no_main_description, resource_types_missing_main_description
    has_main_description = 'description' in metadata
    has_additional_descriptions = len(record_additional_description_sources) > 0

    if has_additional_descriptions and not has_main_description:
        records_with_additional_but_no_main_description += 1
        # Track resource type for this record
        resource_type_id = resource_type.get('id', 'unknown')
        if resource_type_id not in resource_types_missing_main_description:
            resource_types_missing_main_description[resource_type_id] = 0
        resource_types_missing_main_description[resource_type_id] += 1

    # Enhanced logging with additional description info
    additional_desc_info = f", Additional descriptions from {', '.join(record_additional_description_sources) if record_additional_description_sources else 'none'}"
    main_desc_status = "has main description" if has_main_description else "NO MAIN DESCRIPTION"

    logger.info(
        f"Record {record_doi}: Creators from {', '.join(creator_sources) if creator_sources else 'none'}, Publication date from {date_source or 'missing'}{additional_desc_info}, {main_desc_status}")

    # Log error for records with Unknown creators
    if "Unknown" in creator_sources:
        logger.error(f"No creator information found for record: {record_doi}")

    record = {
        'pids': {},
        'metadata': metadata,
        'files': {'enabled': True},  # Mark as metadata-only record (no files)
        'access': {
            'record': 'public',
            'files': 'public'
        }
    }

    # ==================== ACCESS RIGHTS ====================

    # Check for access restrictions (MARC 506)
    access_506 = record_elem.find('.//marc:datafield[@tag="506"]', MARC_NS)
    if access_506 is not None:
        access_a = access_506.find('.//marc:subfield[@code="a"]', MARC_NS)
        if access_a is not None:
            access_text = access_a.text.strip().lower()
            if 'restricted' in access_text or 'embargo' in access_text:
                record['access']['record'] = 'restricted'
                record['access']['files'] = 'restricted'

    # Check for embargo information (MARC 856$e)
    embargo_fields = record_elem.findall('.//marc:datafield[@tag="856"][@ind1="4"]', MARC_NS)
    for embargo_field in embargo_fields:
        embargo_e = embargo_field.find('.//marc:subfield[@code="e"]', MARC_NS)
        if embargo_e is not None:
            embargo_text = embargo_e.text.strip().lower()
            if 'restricted' in embargo_text or 'embargo' in embargo_text:
                record['access']['files'] = 'restricted'

    if custom_fields:
        record['custom_fields'] = custom_fields

    return record


def add_test_file_to_draft(draft, identity):
    """Add test.xml file to the draft record.

    Args:
        draft: The draft record
        identity: User identity for authentication
    """
    try:
        # Path to the test file
        test_file_path = '/home/jabbi/PycharmProjects/chicago-invenio/site/chicago_invenio/scripts/test.xml'

        # Check if test file exists
        import os
        if not os.path.exists(test_file_path):
            logger.warning(f"Test file not found at {test_file_path}, skipping file upload")
            return

        # Get the draft files service
        draft_file_service = current_rdm_records_service.draft_files

        # Initialize file metadata
        file_data = [{"key": "test.xml"}]
        draft_file_service.init_files(identity, draft.id, data=file_data)

        # Upload file content
        with open(test_file_path, "rb") as f:
            draft_file_service.set_file_content(identity, draft.id, "test.xml", f)

        # Commit the file
        draft_file_service.commit_file(identity, draft.id, "test.xml")

        logger.info(f"Successfully uploaded test.xml to draft {draft.id}")

    except Exception as e:
        logger.error(f"Error uploading file to draft {draft.id}: {e}")
        # Don't raise the exception - continue with record creation even if file upload fails


def stream_marc_records(filepath: str, chunk_size: int = 1000) -> Generator[ET.Element, None, None]:
    """Stream MARC records from XML file efficiently.

    Args:
        filepath: Path to the XML file
        chunk_size: Number of records to process at once

    Yields:
        XML elements representing MARC records
    """
    logger.info(f"Starting to stream records from {filepath}")

    try:
        # Use iterparse for memory-efficient parsing
        context = ET.iterparse(filepath, events=('start', 'end'))
        context = iter(context)
        event, root = next(context)

        record_count = 0

        for event, elem in context:
            if event == 'end' and elem.tag.endswith('record'):
                record_count += 1
                # Make a copy of the element before clearing
                record_copy = ET.fromstring(ET.tostring(elem))
                yield record_copy

                # Clear the element to save memory after copying
                elem.clear()
                root.clear()

                if record_count % chunk_size == 0:
                    logger.info(f"Processed {record_count} records...")

    except ET.ParseError as e:
        logger.error(f"XML parsing error: {e}")
        raise
    except Exception as e:
        logger.error(f"Error streaming records: {e}")
        raise


def process_records_batch(records_batch, owner_id: int) -> list:
    """Process a batch of records.

    Args:
        records_batch: List of XML record elements
        owner_id: ID of the record owner

    Returns:
        List of created record IDs
    """
    results = []
    identity = get_authenticated_identity(owner_id)

    for record_elem in records_batch:
        invenio_data = None
        try:
            # Convert MARC to InvenioRDM format
            invenio_data = parse_marc_record(record_elem)
            print(invenio_data)

            # Create draft record
            draft = current_rdm_records_service.create(
                data=invenio_data,
                identity=identity
            )

            # Add test file to the draft
            add_test_file_to_draft(draft, identity)

            # Publish the record
            published = current_rdm_records_service.publish(
                id_=draft.id,
                identity=identity
            )

            results.append(published.id)

        except Exception as e:
            logger.error(f"Error processing record: {e}")
            logger.info(invenio_data)
            continue

    return results


@click.command("xml_import_data")
@click.argument("email")
@click.argument("filepath")
@click.option("--batch-size", default=100, help="Number of records to process in each batch")
@click.option("--max-records", default=1000, type=int, help="Maximum number of records to process (for testing)")
def xml_import_data(email: str, filepath: str, batch_size: int, max_records: Optional[int]):
    """Import MARCXML bibliographic data into Chicago Invenio.

    Args:
        email: Email of the user who will own the records
        filepath: Path to the MARCXML file
        batch_size: Number of records to process in each batch
        max_records: Maximum number of records to process (optional, for testing)
    """
    # Create application context
    app = create_app()
    with app.app_context():
        # Find the user
        user_datastore = current_app.extensions["security"].datastore
        owner = user_datastore.find_user(email=email)

        if not owner:
            click.secho(f"User with email {email} not found.", fg="red")
            sys.exit(1)

        logger.info(f"Starting XML import for user: {email}")
        logger.info(f"File: {filepath}")
        logger.info(f"Batch size: {batch_size}")

        start_time = time.time()
        total_processed = 0
        total_created = 0

        try:
            # Stream records from XML file
            record_stream = stream_marc_records(filepath)

            # Process records in batches
            while True:
                batch = list(islice(record_stream, batch_size))
                if not batch:
                    break

                # Check max_records limit
                if max_records and total_processed >= max_records:
                    logger.info(f"Reached maximum records limit: {max_records}")
                    break

                # Process the batch
                batch_results = process_records_batch(batch, owner.id)

                total_processed += len(batch)
                total_created += len(batch_results)

                logger.info(
                    f"Batch complete: {len(batch)} processed, "
                    f"{len(batch_results)} created. "
                    f"Total: {total_processed} processed, {total_created} created"
                )

                # Check max_records limit after processing
                if max_records and total_processed >= max_records:
                    break

        except Exception as e:
            logger.error(f"Import failed: {e}")
            sys.exit(1)

        # Calculate elapsed time
        end_time = time.time()
        elapsed_time = end_time - start_time
        minutes, seconds = divmod(elapsed_time, 60)

        # Final report
        logger.info("=" * 50)
        logger.info("IMPORT COMPLETE")
        logger.info(f"Total records processed: {total_processed}")
        logger.info(f"Total records created: {total_created}")
        logger.info(f"Success rate: {(total_created / total_processed) * 100:.1f}%" if total_processed > 0 else "N/A")

        if minutes:
            logger.info(f"Time taken: {int(minutes)} minutes and {seconds:.2f} seconds")
        else:
            logger.info(f"Time taken: {seconds:.2f} seconds")

        if total_processed > 0:
            rate = total_processed / elapsed_time
            logger.info(f"Processing rate: {rate:.2f} records/second")

        # Creator source statistics
        logger.info("")
        logger.info("CREATOR SOURCE STATISTICS")
        logger.info("-" * 30)
        total_creator_records = sum(creator_source_counts.values())
        if total_creator_records > 0:
            for source, count in creator_source_counts.items():
                percentage = (count / total_creator_records) * 100
                logger.info(f"MARC {source}: {count} records ({percentage:.1f}%)")
        else:
            logger.info("No creator source data available")

        # Publication date source statistics
        logger.info("")
        logger.info("PUBLICATION DATE SOURCE STATISTICS")
        logger.info("-" * 40)
        total_date_records = sum(date_source_counts.values())
        if total_date_records > 0:
            for source, count in date_source_counts.items():
                percentage = (count / total_date_records) * 100
                logger.info(f"MARC {source}: {count} records ({percentage:.1f}%)")
        else:
            logger.info("No date source data available")

        # Additional description source statistics
        logger.info("")
        logger.info("ADDITIONAL DESCRIPTION SOURCE STATISTICS")
        logger.info("-" * 45)
        total_additional_desc_fields = sum(additional_description_source_counts.values())
        if total_additional_desc_fields > 0:
            for source, count in additional_description_source_counts.items():
                percentage = (count / total_additional_desc_fields) * 100
                logger.info(f"MARC {source}: {count} fields ({percentage:.1f}%)")

            logger.info("")
            logger.info(
                f"Records with additional descriptions but NO main description (520$a): {records_with_additional_but_no_main_description}")
            if total_processed > 0:
                no_main_desc_percentage = (records_with_additional_but_no_main_description / total_processed) * 100
                logger.info(
                    f"Percentage of records with additional descriptions but no main description: {no_main_desc_percentage:.1f}%")

            # Report resource types for records missing main descriptions
            if resource_types_missing_main_description:
                logger.info("")
                logger.info("RESOURCE TYPES FOR RECORDS MISSING MAIN DESCRIPTION")
                logger.info("-" * 55)
                for resource_type_id, count in sorted(resource_types_missing_main_description.items(),
                                                      key=lambda x: x[1], reverse=True):
                    percentage = (count / records_with_additional_but_no_main_description) * 100
                    logger.info(f"Resource type '{resource_type_id}': {count} records ({percentage:.1f}%)")
        else:
            logger.info("No additional description source data available")

        logger.info("=" * 50)


if __name__ == "__main__":
    xml_import_data()