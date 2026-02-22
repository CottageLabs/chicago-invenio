"""Script to import XML bibliographic data for the Chicago Invenio repository.

Make sure the Invenio services have been set up and are running.

Efficiently processes large MARCXML files using streaming XML parsing.

The user used will become the record owner for all imported records. That user
needs to be an admin user in order for internal notes to work.

To run the script, go to the repository root directory and use the following command:

        $ pipenv run invenio shell site/chicago_invenio/scripts/import_data.py <email> <datafile> <filepath>

Where:

    email: Email of the user to assign as record owner
    datafile: Path to the MARCXML data file to import
    filepath: Path to the directory where any associated files are stored (they are looked up under their TIND ID)
"""
from datetime import datetime

import click
import logging
import sys
import time
import json
from typing import Dict, Any, Optional, Generator, Tuple, List
import xml.etree.ElementTree as ET
from itertools import islice
import re
import os
import html
import idutils
import requests
from urllib.parse import unquote
from flask import current_app
from invenio_app.factory import create_app
from flask_principal import Identity, RoleNeed, UserNeed
from invenio_access.permissions import any_user, authenticated_user
from invenio_rdm_records.proxies import (
    current_rdm_records_service,
    current_record_communities_service,
)
from invenio_records_resources.services.records.results import RecordItem
from invenio_requests.proxies import current_requests_service
from load_as_coms_colls import main as get_create_community_collection_structure, CSV
from chicago_invenio.scripts.community_assignment_algorithm import CommunityAssignmentAlgorithm
from chicago_invenio.scripts.utils import slugify


def get_identity_with_roles(user):
    """Create an identity that includes the user's roles.

    The default get_authenticated_identity() doesn't load roles,
    so admin/curator permissions don't work.
    """
    identity = Identity(user.id)
    identity.provides.add(UserNeed(user.id))
    identity.provides.add(authenticated_user)
    identity.provides.add(any_user)

    # Add all user roles
    for role in user.roles:
        identity.provides.add(RoleNeed(role.name))

    return identity


def strip_html_tags(text):
    """Remove HTML tags and decode HTML entities from text"""
    if not text:
        return text
    # Remove HTML tags using regex
    clean = re.sub('<.*?>', '', text)
    # Decode HTML entities (like &amp; &lt; &gt; etc.)
    clean = html.unescape(clean)
    return clean.strip()


def map_description_type(desc_type):
    """Map MARC description types to DataCite vocabulary IDs"""
    if not desc_type:
        return 'abstract'
    
    # Convert to lowercase for mapping
    desc_lower = desc_type.lower().strip()
    
    # Mapping table for specific MARC values to DataCite vocabulary IDs
    type_mappings = {
        'tableofcontents': 'table-of-contents',
        'technicalinfo': 'technical-info'
    }
    
    return type_mappings.get(desc_lower, desc_lower)

def add_pages(resource_type, phys_text):
    # For textual resource types, append "pages" to numeric values as per CSV mapping
    textual_types = [
        'publication-article', 'publication-book', 'publication-section',
        'publication-thesis', 'publication-dissertation', 'publication-report'
    ]

    if resource_type.get('id') in textual_types:
        if phys_text.isdigit():
            return True

        digit_range = [d.strip() for d in phys_text.split('-') if d.strip().isdigit()]
        if len(digit_range) == 2:
            return True

    return False

# Functions moved back to avoid circular import

# Configure logging with timestamped filename
import_timestamp = time.strftime("%Y%m%d_%H%M%S")
log_filename = f'import_{import_timestamp}.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename),
        logging.FileHandler('import_latest.log'),  # Always overwrite latest
        logging.StreamHandler()  # Also log to console
    ]
)
logger = logging.getLogger(__name__)

# Log the log filename for reference
logger.info(f"Import logging to: {log_filename}")


# Global error tracking
errors_log = []
warnings_log = []

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
    'image': 'image'
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
    'fre': 'fra', # French (alternative 3-letter code)
    'de': 'deu',  # German
    'ger': 'deu', # German (alternative 3-letter code)
    'it': 'ita',  # Italian
    'pt': 'por',  # Portuguese
    'ru': 'rus',  # Russian
    'zh': 'zho',  # Chinese
    'chi': 'zho', # Chinese (3-letter code)
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
    'cc0': 'cc0-1.0',
    'attribution-noncommercial 4.0 international': 'cc-by-nc-4.0',
    'attribution-noncommercial-noderivatives 4.0 international': 'cc-by-nc-nd-4.0',
    'attribution-noncommercial-sharealike 4.0 international': 'cc-by-nc-sa-4.0',
}

ORG_WORDS = ['center', 'institute', 'university', 'foundation', 'study', 'statistics', 'administration',
             'department', 'office', 'agency', 'committee', 'society', 'association', 'corporation', 'company',
             'laboratory', 'lab', 'council', 'board', 'museum', 'library', 'school', 'college', 'firm', 'group',
             'club', 'church', 'party', 'government', 'corporation', 'press', 'publisher', 'organization',
             'organisation']


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
    """Parse MARC corporate name field into InvenioRDM format."""
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

    def is_valid_month(month_str: str) -> bool:
        """Check if month string is valid (01-12)."""
        try:
            month = int(month_str)
            return 1 <= month <= 12
        except ValueError:
            return False

    def is_valid_day(day_str: str) -> bool:
        """Check if day string is valid (01-31)."""
        try:
            day = int(day_str)
            return 1 <= day <= 31
        except ValueError:
            return False

    # Try to match various date formats
    # YYYY-MM-DD format
    match = re.search(r'(19|20)\d{2}-(\d{2})-(\d{2})', date_text)
    if match:
        month, day = match.group(2), match.group(3)
        if is_valid_month(month) and is_valid_day(day):
            return match.group()

    # YYYY/MM/DD format
    match = re.search(r'(19|20)\d{2}/(\d{2})/(\d{2})', date_text)
    if match:
        month, day = match.group(2), match.group(3)
        if is_valid_month(month) and is_valid_day(day):
            date_parts = match.group().split('/')
            return f"{date_parts[0]}-{date_parts[1]}-{date_parts[2]}"

    # YYYY-MM format
    match = re.search(r'(19|20)\d{2}-(\d{2})', date_text)
    if match:
        month = match.group(2)
        if is_valid_month(month):
            return match.group()

    # YYYY/MM format
    match = re.search(r'(19|20)\d{2}/(\d{2})', date_text)
    if match:
        month = match.group(2)
        if is_valid_month(month):
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
    """Scrape publication date from DOI URL."""
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

        return None

    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to fetch DOI {doi}: {e}")
        return None
    except Exception as e:
        logger.warning(f"Error scraping DOI {doi}: {e}")
        return None


def add_orcid_if_valid(person_data: Dict[str, Any], orcid_field) -> None:
    """Add ORCID identifier to person data if present and valid."""
    if orcid_field is not None:
        orcid_id = orcid_field.text.strip()
        if 'orcid.org' in orcid_id:
            orcid_id = orcid_id.split('/')[-1]  # Extract just the ID
        # Validate ORCID format (should be XXXX-XXXX-XXXX-XXXX)
        if len(orcid_id) == 19 and orcid_id.count('-') == 3:
            person_data["person_or_org"]["identifiers"] = [{
                "identifier": orcid_id,
                "scheme": "orcid"
            }]

def determine_resource_type(record_elem) -> Dict[str, str]:
    """Determine resource type from MARC record."""
    # Check MARC 336 (Content Type) - primary source per CSV mapping
    content_type_field = record_elem.find('.//marc:datafield[@tag="336"]', MARC_NS)
    if content_type_field is not None:
        content_type_a = content_type_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if content_type_a is not None:
            content_type = content_type_a.text.strip().lower()
            # Sort mappings by key length (longest first) to match specific terms before generic ones
            for key, value in sorted(RESOURCE_TYPE_MAPPINGS.items(), key=lambda x: len(x[0]), reverse=True):
                if key in content_type:
                    return {'id': value}

    # Fallback: Check MARC 983 (Local resource type)
    local_type_field = record_elem.find('.//marc:datafield[@tag="983"]', MARC_NS)
    if local_type_field is not None:
        type_a = local_type_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if type_a is not None:
            type_text = type_a.text.strip().lower()
            # Sort mappings by key length (longest first) to match specific terms before generic ones
            for key, value in sorted(RESOURCE_TYPE_MAPPINGS.items(), key=lambda x: len(x[0]), reverse=True):
                if key in type_text:
                    return {'id': value}

    # Default to other
    return {'id': 'other'}


def extract_ror_id_from_identifier(identifier: str) -> Optional[str]:
    """Extract ROR ID from various identifier formats using idutils."""
    if not identifier:
        logger.debug("extract_ror_id_from_identifier: empty identifier")
        return None

    # List of known invalid ROR IDs to ignore
    INVALID_ROR_IDS = {'01gj55p76', '05s2rj042', '110007622'}

    identifier = identifier.strip()
    logger.debug(f"extract_ror_id_from_identifier: processing '{identifier}'")

    # Check if it contains ror.org pattern and extract the ID
    if 'ror.org/' in identifier.lower():
        logger.debug(f"extract_ror_id_from_identifier: ROR pattern detected '{identifier}'")
        # Extract the ROR ID from the pattern (works for URLs and partial URLs)
        ror_match = re.search(r'ror\.org/([0-9a-z]+)', identifier.lower())
        if ror_match:
            extracted_id = ror_match.group(1)
            logger.debug(f"extract_ror_id_from_identifier: extracted '{extracted_id}'")
            # Check if it's in the invalid list
            if extracted_id in INVALID_ROR_IDS:
                logger.debug(f"extract_ror_id_from_identifier: ignoring invalid ROR ID '{extracted_id}'")
                return None
            # Validate the extracted ID
            if idutils.is_ror(extracted_id):
                logger.debug(f"extract_ror_id_from_identifier: valid ROR ID '{extracted_id}'")
                return extracted_id
            else:
                logger.debug(f"extract_ror_id_from_identifier: invalid ROR ID '{extracted_id}'")

    # Check if it's already a plain ROR ID (not a URL)
    elif idutils.is_ror(identifier) and not idutils.is_url(identifier):
        logger.debug(f"extract_ror_id_from_identifier: direct ROR ID '{identifier}'")
        # Check if it's in the invalid list
        if identifier in INVALID_ROR_IDS:
            logger.debug(f"extract_ror_id_from_identifier: ignoring invalid ROR ID '{identifier}'")
            return None
        return identifier

    logger.debug(f"extract_ror_id_from_identifier: no valid ROR ID found in '{identifier}'")
    return None


def parse_marc_record(record_elem, record_identifier) -> Tuple[Dict[str, Any], List[Dict]]:
    """Convert MARCXML record to InvenioRDM format.

    Args:
        record_elem: XML element containing a MARC record

    Returns:
        Dictionary with InvenioRDM record data
    """
    metadata = {'publisher': "University of Chicago"}
    custom_fields = {'chicago:tind_id': int(record_identifier)}
    pids = {}

    # ==================== RESOURCE TYPE ====================

    resource_type = determine_resource_type(record_elem)
    metadata['resource_type'] = resource_type

    # ==================== CREATORS AND CONTRIBUTORS ====================

    creators = []
    contributors = []

    # Extract additional personal creators (MARC 700)
    added_personal = record_elem.findall('.//marc:datafield[@tag="700"]', MARC_NS)
    for personal_field in added_personal:
        # Check if this is actually an organizational name in a 700 field
        subfield_a = personal_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if subfield_a is not None:
            name_text = subfield_a.text.strip()
            # Check for organizational indicators
            if any(word in name_text.lower() for word in ORG_WORDS):
                # Treat as organizational creator
                creator_data = {
                    "person_or_org": {
                        "type": "organizational",
                        "name": name_text
                    }
                }
                # Add affiliation if present
                subfield_u = personal_field.find('.//marc:subfield[@code="u"]', MARC_NS)
                if subfield_u is not None:
                    creator_data["affiliations"] = [{"name": subfield_u.text.strip()}]
            else:
                # Process as personal name
                creator_data = parse_personal_name(personal_field)
        else:
            creator_data = None
            
        if creator_data:
            # Add ORCID if present
            contrib_orcid = personal_field.find('.//marc:subfield[@code="1"]', MARC_NS)
            add_orcid_if_valid(creator_data, contrib_orcid)

            # Check if there are contributor-specific role indicators
            role_e = personal_field.find('.//marc:subfield[@code="e"]', MARC_NS)
            role_4 = personal_field.find('.//marc:subfield[@code="4"]', MARC_NS)

            # If explicit contributor roles are found, add as contributor instead
            if role_e is not None or role_4 is not None:
                role = None
                if role_e is not None:
                    role_text = role_e.text.strip().lower()
                    role = CONTRIBUTOR_ROLE_MAPPINGS.get(role_text, 'contributor')
                elif role_4 is not None:
                    role = role_4.text.strip()

                if role:
                    creator_data['role'] = {'id': role}
                else:
                    creator_data['role'] = {'id': 'other'}
                
                contributors.append(creator_data)
            else:
                # No specific role - add as creator
                creators.append(creator_data)


    # Extract inventors (MARC 701)
    inventor_fields = record_elem.findall('.//marc:datafield[@tag="701"]', MARC_NS)
    for inventor_field in inventor_fields:
        if inventor_field.get('ind1') == '1':  # Personal name
            inventor_data = parse_personal_name(inventor_field)
            if inventor_data:
                inventor_data['role'] = {'id': 'inventor'}
                # For patents, promote inventors to creators; otherwise add as contributors
                if resource_type['id'] == 'publication-patent':
                    creators.append(inventor_data)
                else:
                    contributors.append(inventor_data)

    # Extract patent applicant (MARC 712)
    applicant_fields = record_elem.findall('.//marc:datafield[@tag="712"]', MARC_NS)
    for applicant_field in applicant_fields:
        if applicant_field.get('ind1') == '1':  # Personal/organizational name
            applicant_data = parse_corporate_name(applicant_field)
            if applicant_data:
                applicant_data['role'] = {'id': 'patent_applicant'}
                contributors.append(applicant_data)

    # Extract patent assignee (MARC 713)
    assignee_fields = record_elem.findall('.//marc:datafield[@tag="713"]', MARC_NS)
    for assignee_field in assignee_fields:
        if assignee_field.get('ind1') == '1':  # Personal/organizational name
            assignee_data = parse_corporate_name(assignee_field)
            if assignee_data:
                assignee_data['role'] = {'id': 'patent_assignee'}
                contributors.append(assignee_data)

    # Extract additional contributors from local/variant fields (MARC 701-713)
    for tag in ['701', '702', '703', '712', '713']:
        variant_fields = record_elem.findall(f'.//marc:datafield[@tag="{tag}"]', MARC_NS)
        for field in variant_fields:
            if tag in ['701', '702', '703']:  # Personal name variants
                contributor_data = parse_personal_name(field)
            else:  # Corporate name variants
                contributor_data = parse_corporate_name(field)

            if contributor_data:
                # Add required role field for contributors
                contributor_data['role'] = {'id': 'other'}
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
            role = 'other'  # default
            if contrib_role is not None:
                role_text = contrib_role.text.strip().lower()
                if role_text in CONTRIBUTOR_ROLE_MAPPINGS:
                    role = CONTRIBUTOR_ROLE_MAPPINGS[role_text]
                elif role_text in ['advisor']:
                    role = 'advisor'
                elif role_text in ['supervisor']:
                    role = 'supervisor'
                elif role_text == 'sponsor':
                    role = 'sponsor'

            # Check for special roles based on indicators
            if contrib_field.get('ind1') == '1':
                if contrib_field.get('ind2') == '1':
                    role = 'editor'  # Editor
                elif contrib_field.get('ind2') == '2':
                    role = 'advisor'  # Advisor
                elif contrib_field.get('ind2') == '4':
                    role = 'committeemember'  # Committee member
                elif contrib_field.get('ind2') == '5':
                    role = 'interviewee'  # Interviewee

            # Use parse_personal_name for consistent name handling
            if any(word in name_text.lower() for word in ORG_WORDS):
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
            add_orcid_if_valid(contributor_data, contrib_orcid)

            # Add affiliation if present
            if contrib_affiliation is not None:
                contributor_data["affiliations"] = [{"name": contrib_affiliation.text.strip()}]

            contributors.append(contributor_data)
            
    # Deduplicate creators to avoid duplicates from multiple MARC fields
    if creators:
        seen_creators = []
        unique_creators = []
        for creator in creators:
            # Create a unique identifier for each creator
            creator_key = (
                creator["person_or_org"]["type"],
                creator["person_or_org"]["name"],
                tuple(aff["name"] for aff in creator.get("affiliations", []))
            )
            if creator_key not in seen_creators:
                seen_creators.append(creator_key)
                unique_creators.append(creator)
        creators = unique_creators

    # Deduplicate contributors to avoid duplicates from multiple MARC fields
    # Role-agnostic deduplication but prioritize non-"other" roles
    # Also exclude anyone who is already listed as a creator
    if contributors:
        # Create a set of creator keys to exclude from contributors
        creator_keys = set()
        for creator in creators:
            creator_key = (
                creator["person_or_org"]["type"],
                creator["person_or_org"]["name"],
                tuple(aff["name"] for aff in creator.get("affiliations", []))
            )
            creator_keys.add(creator_key)
        
        seen_contributors = {}
        unique_contributors = []
        for contributor in contributors:
            # Create a unique identifier for each contributor (excluding role)
            contributor_key = (
                contributor["person_or_org"]["type"],
                contributor["person_or_org"]["name"],
                tuple(aff["name"] for aff in contributor.get("affiliations", []))
            )
            
            # Skip contributors who are already creators
            if contributor_key in creator_keys:
                continue
            
            current_role = contributor.get("role", {}).get("id", "other")
            
            if contributor_key not in seen_contributors:
                # First occurrence of this contributor
                seen_contributors[contributor_key] = contributor
                unique_contributors.append(contributor)
            else:
                # Duplicate found - keep the one with better role priority
                existing_role = seen_contributors[contributor_key].get("role", {}).get("id", "other")
                
                # If existing role is "other" and current role is not "other", replace it
                if existing_role == "other" and current_role != "other":
                    # Find and replace the existing contributor
                    for i, uc in enumerate(unique_contributors):
                        uc_key = (
                            uc["person_or_org"]["type"],
                            uc["person_or_org"]["name"],
                            tuple(aff["name"] for aff in uc.get("affiliations", []))
                        )
                        if uc_key == contributor_key:
                            unique_contributors[i] = contributor
                            seen_contributors[contributor_key] = contributor
                            break
                # If both are "other" or current is "other" and existing is not, keep existing
        
        contributors = unique_contributors

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

    # Final fallback - create unknown creator
    if not creators:
        creators = [{
            "person_or_org": {
                "type": "organizational",
                "name": "Unknown"
            }
        }]

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

        title = strip_html_tags(title_a.text.strip()) if title_a is not None else "Untitled"
        if title_b is not None:
            title += f": {strip_html_tags(title_b.text.strip())}"

        metadata['title'] = title
    else:
        metadata['title'] = "Untitled"

    # ==================== ALTERNATIVE TITLES ====================
    
    additional_titles = []
    
    # Variant Titles (MARC 246)
    variant_title_fields = record_elem.findall('.//marc:datafield[@tag="246"]', MARC_NS)
    for variant_field in variant_title_fields:
        variant_title_a = variant_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        variant_lang_g = variant_field.find('.//marc:subfield[@code="g"]', MARC_NS)
        
        if variant_title_a is not None and variant_title_a.text and variant_title_a.text.strip():
            title_entry = {
                "title": variant_title_a.text.strip(),
                "type": {
                    "id": "alternative-title",
                    "title": {"en": "Alternative Title"}
                }
            }
            
            # Add language if present
            if variant_lang_g is not None:
                lang_code = variant_lang_g.text.strip().lower()
                # Convert 2-letter to 3-letter codes if needed
                if len(lang_code) == 2 and lang_code in LANGUAGE_MAPPINGS:
                    lang_code = LANGUAGE_MAPPINGS[lang_code]
                elif len(lang_code) == 3:
                    pass  # Already 3-letter
                else:
                    logger.warning(f"Unknown language code in 246$g: {lang_code}")
                    lang_code = None
                    
                if lang_code:
                    title_entry["lang"] = {"id": lang_code}
            
            additional_titles.append(title_entry)
    
    if additional_titles:
        metadata['additional_titles'] = additional_titles

    # ==================== VERSION ====================

    version_field = record_elem.find('.//marc:datafield[@tag="251"]', MARC_NS)
    if version_field is not None:
        version_a = version_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if version_a is not None:
            metadata['version'] = version_a.text.strip()

    # ==================== IDENTIFIERS ====================

    identifiers = []

    # DOI and other identifiers (MARC 024)
    identifier_024_fields = record_elem.findall('.//marc:datafield[@tag="024"]', MARC_NS)
    for id_field in identifier_024_fields:
        subfield_a = id_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        subfield_d = id_field.find('.//marc:subfield[@code="d"]', MARC_NS)
        subfield_2 = id_field.find('.//marc:subfield[@code="2"]', MARC_NS)

        # TODO 024-7-2 should be parent doi?
        # Handle DOI identifiers (024$7$2="doi")
        if (id_field.get('ind1') == '7' and subfield_2 is not None and
                subfield_2.text.strip().lower() == 'doi' and subfield_a is not None):
            doi_value = subfield_a.text.strip()
            # Validate DOI using idutils
            if idutils.is_doi(doi_value):
                datacite_prefix = current_app.config["DATACITE_PREFIX"]
                # Assign DOIs with our prefix as managed by DataCite
                if doi_value.startswith(datacite_prefix):
                    pids['doi'] = {'identifier': doi_value,
                                   'provider': 'datacite',}
                    with open('doi_mapping.txt', 'a') as f:
                        f.write(f"{record_identifier},{doi_value}\n")
                else:
                    identifiers.append({
                        'identifier': doi_value,
                        'scheme': 'doi'
                    })
            else:
                logger.error(f"Invalid DOI found: {doi_value}")

        # Handle patent numbers (MARC 024$a)
        elif subfield_a is not None:
            id_value = subfield_a.text.strip()
            if id_value and not any(existing['identifier'] == id_value for existing in identifiers):
                # There are some DOIs erroneously placed in 024$a, so check for DOI pattern first
                # it's fine to add these as DOIs
                if idutils.is_doi(id_value):
                    identifiers.append({
                        'identifier': id_value,
                        'scheme': 'doi'
                    })
                # Assign as patent number
                else:
                    identifiers.append({
                        'identifier': id_value,
                        'scheme': 'patent_number'
                    })

        # Handle patent application numbers (MARC 024$d)
        if subfield_d is not None:
            id_value = subfield_d.text.strip()
            if id_value and not any(existing['identifier'] == id_value for existing in identifiers):
                # Patent application numbers
                identifiers.append({
                    'identifier': id_value,
                    'scheme': 'patent_application_number'
                })

    # ISSN (MARC 022$a)
    #issn_fields = record_elem.findall('.//marc:datafield[@tag="022"]', MARC_NS)
    #for issn_field in issn_fields:
    #    issn_a = issn_field.find('.//marc:subfield[@code="a"]', MARC_NS)
    #    if issn_a is not None:
    #        issn_value = issn_a.text.strip()
    #        if issn_value and not any(existing['identifier'] == issn_value for existing in identifiers):
    #            identifiers.append({
    #                'identifier': issn_value,
    #                'scheme': 'issn'
    #            })

    # Electronic location/URLs (MARC 856)
    url_fields = record_elem.findall('.//marc:datafield[@tag="856"]', MARC_NS)
    file_information = []
    logger.info(f"Found {len(url_fields)} URL fields (856) in record")
    for url_field in url_fields:
        url_u = url_field.find('.//marc:subfield[@code="u"]', MARC_NS)
        if url_u is not None:
            url_text = url_u.text.strip()
            logger.info(f"Processing URL: {url_text}")
            # Add as identifier If this is a valid URL and not a UChicago knowledge base link
            if url_text.startswith('http') and 'knowledge.uchicago.edu' not in url_text:
                identifiers.append({
                    'identifier': url_text,
                    'scheme': 'url'
                })
                logger.info(f"Added as external identifier")
            else:
                # File description (MARC 856$y)
                url_y = url_field.find('.//marc:subfield[@code="y"]', MARC_NS)
                file_name = unquote(url_text.split('/')[-1])  # Extract file name from URL
                logger.info(f"Extracted filename: {file_name}")

                if url_y is not None:
                    description = url_y.text.strip()
                    # Collect file information for file description handling
                    file_information.append({'url': file_name, 'description': description})
                    logger.info(f"Added file info - filename: {file_name}, description: {description[:50]}...")
                else:
                    logger.info(f"No description (subfield y) found for {file_name}")

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


    # Publication info (MARC 260)
    pub_fields_260 = record_elem.findall('.//marc:datafield[@tag="260"]', MARC_NS)
    for pub_field_260 in pub_fields_260:
        # Publisher name (from first field that has it) - overrides default
        pub_b = pub_field_260.find('.//marc:subfield[@code="b"]', MARC_NS)
        if pub_b is not None:
            metadata['publisher'] = pub_b.text.strip()
            break  # Use first publisher found

        # Publication date - prioritize $c for patents, skip for others to avoid interference
        pub_c = pub_field_260.find('.//marc:subfield[@code="c"]', MARC_NS)
        if pub_c is not None:
            # For patents only, use 260$c as publication date
            if resource_type['id'] == 'publication-patent':
                date = extract_full_date(pub_c.text.strip())
                if date:
                    metadata['publication_date'] = date
                    break  # Stop after finding first valid $c date

    # ==================== DATES (ADDITIONAL) ====================
    
    dates = []
    
    # Patent filing date (MARC 260$g) - only for patents
    resource_type_id = resource_type.get('id', '')
    if resource_type_id == 'publication-patent':
        pub_fields_260 = record_elem.findall('.//marc:datafield[@tag="260"]', MARC_NS)
        for pub_field_260 in pub_fields_260:
            pub_g = pub_field_260.find('.//marc:subfield[@code="g"]', MARC_NS)
            if pub_g is not None:
                filing_date = extract_full_date(pub_g.text.strip())
                if filing_date:
                    dates.append({
                        'date': filing_date,
                        'type': {
                            'id': 'patent-filed',
                            'title': {'en': 'Patent Filed'}
                        }
                    })
                    break
    
    # Relevant dates (MARC 518)
    relevant_date_fields = record_elem.findall('.//marc:datafield[@tag="518"]', MARC_NS)
    for date_field in relevant_date_fields:
        date_d = date_field.find('.//marc:subfield[@code="d"]', MARC_NS)
        date_type_o = date_field.find('.//marc:subfield[@code="o"]', MARC_NS)
        
        if date_d is not None:
            date_value = extract_full_date(date_d.text.strip())
            if date_value:
                date_entry = {'date': date_value}
                
                # Add type if present, or default for interviews
                if date_type_o is not None:
                    type_text = date_type_o.text.strip()
                    date_entry['type'] = {
                        'id': type_text.lower(),
                        'title': {'en': type_text}
                    }
                else:
                    # Check if this is an interview and use "collected" as default
                    content_type_field = record_elem.find('.//marc:datafield[@tag="336"]', MARC_NS)
                    if content_type_field is not None:
                        content_type_a = content_type_field.find('.//marc:subfield[@code="a"]', MARC_NS)
                        if content_type_a is not None and content_type_a.text.strip().lower() == 'interview':
                            date_entry['type'] = {
                                'id': 'collected',
                                'title': {'en': 'Collected'}
                            }
                
                dates.append(date_entry)
    
    if dates:
        metadata['dates'] = dates

    # Additional date information (MARC 269)
    date_269 = record_elem.find('.//marc:datafield[@tag="269"]', MARC_NS)
    if date_269 is not None:
        date_a = date_269.find('.//marc:subfield[@code="a"]', MARC_NS)
        if date_a is not None:
            date = extract_full_date(date_a.text.strip())
            if date:
                metadata['publication_date'] = date

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
            # Otherwise try Date 2
            elif date2.isdigit() and 1000 <= int(date2) <= 2100:
                metadata['publication_date'] = date2

        # Try copyright date (MARC 264 ind2="4")
        if 'publication_date' not in metadata:
            copyright_field = record_elem.find('.//marc:datafield[@tag="264"][@ind2="4"]', MARC_NS)
            if copyright_field is not None:
                copyright_c = copyright_field.find('.//marc:subfield[@code="c"]', MARC_NS)
                if copyright_c is not None:
                    date = extract_full_date(copyright_c.text.strip())
                    if date:
                        metadata['publication_date'] = date

        # Try creation date (MARC 046)
        if 'publication_date' not in metadata:
            creation_field = record_elem.find('.//marc:datafield[@tag="046"]', MARC_NS)
            if creation_field is not None:
                creation_k = creation_field.find('.//marc:subfield[@code="k"]', MARC_NS)  # Beginning date
                if creation_k is not None:
                    date = extract_full_date(creation_k.text.strip())
                    if date:
                        metadata['publication_date'] = date

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
                            break

                    # Fallback: Physical Review D volume mapping if scraping fails
                    phys_rev_d_match = re.search(r'10\.1103/PhysRevD\.(\d+)\.', doi)
                    if phys_rev_d_match:
                        volume = int(phys_rev_d_match.group(1))
                        # PhysRevD volume to year mapping (approximate)
                        if volume >= 85:  # Starting from known volume/year
                            year = str(2012 + (volume - 85) // 2)  # ~2 volumes per year
                            metadata['publication_date'] = year
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
                # Check mappings first (handles both 2-digit and alternate 3-digit codes)
                if lang_code in LANGUAGE_MAPPINGS:
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
        # TODO Should this be a controlled vocabulary term with scheme?
        # 'id' instead of 'subject'?
        if subfield_a is not None:
            subjects.append({'subject': subfield_a.text.strip()})

    # Uncontrolled terms (MARC 653)
    subject_653_fields = record_elem.findall('.//marc:datafield[@tag="653"]', MARC_NS)
    for subject_field in subject_653_fields:
        subfield_a = subject_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if subfield_a is not None:
            # Some fields contain semi-colon separated values
            subfield_a = subfield_a.text.strip().split(';')
            # Omit empty string
            a_subfields = [term.strip() for term in subfield_a if term.strip()]
            for term in a_subfields:
                subjects.append({'subject': term.strip()})

    # LC subject headings (MARC 691)
    all_691_fields = record_elem.findall(f'.//marc:datafield[@tag="691"]', MARC_NS)
    depts = []
    for lc_field in all_691_fields:
        subfield_1 = lc_field.find('.//marc:subfield[@code="1"]', MARC_NS)
        subfield_a = lc_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if subfield_1 is not None:
            subjects.append({'subject': subfield_a.text.strip()})
        else:
            # Convert to vocabulary ID format using slugify
            depts.append({"id": slugify(subfield_a.text.strip())})

    if subjects:
        metadata['subjects'] = subjects

    if depts:
        custom_fields['chicago:department'] = depts

    # ==================== DESCRIPTION/ABSTRACT ====================
    
    additional_descriptions = []  # Initialize once at the beginning

    # Handle main description/abstract (MARC 520$a)
    desc_fields_520 = record_elem.findall('.//marc:datafield[@tag="520"]', MARC_NS)
    main_description_set = False
    
    for desc_field in desc_fields_520:
        desc_a = desc_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        desc_type_7 = desc_field.find('.//marc:subfield[@code="7"]', MARC_NS)
        
        if desc_a is not None:
            desc_text = desc_a.text.strip()
            # Ignore "No abstract" values
            if desc_text.lower() != "no abstract":
                # Check if this should be main description or additional
                if not main_description_set and (desc_type_7 is None or 
                   desc_type_7.text.strip().lower() in ['abstract', '']):
                    metadata['description'] = desc_text
                    main_description_set = True
                else:
                    # Add to additional descriptions with type
                    
                    desc_type = "Abstract"
                    if desc_type_7 is not None:
                        desc_type = desc_type_7.text.strip()
                    
                    mapped_type_id = map_description_type(desc_type)
                    additional_descriptions.append({
                        'description': desc_text,
                        'type': {'id': mapped_type_id, 'title': {'en': desc_type}}
                    })

    # Handle MARC 590 (Local Note) - should be description if no main description
    desc_590_fields = record_elem.findall('.//marc:datafield[@tag="590"]', MARC_NS)
    for desc_field in desc_590_fields:
        desc_a = desc_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if desc_a is not None:
            desc_text = desc_a.text.strip()
            if not main_description_set:
                metadata['description'] = desc_text
                main_description_set = True
            else:
                additional_descriptions.append({
                    'description': desc_text,
                    'type': {'id': 'abstract', 'title': {'en': 'Abstract'}}
                })

    # ==================== ADDITIONAL DESCRIPTIONS ====================

    # Administrative notes (MARC 592) - internal use only
    note_592_fields = record_elem.findall('.//marc:datafield[@tag="592"]', MARC_NS)
    internal_notes = []
    for note_field in note_592_fields:
        note_a = note_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if note_a is not None:
            internal_notes.append({'note': note_a.text.strip()})

    # ==================== ADDITIONAL DESCRIPTIONS ====================

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

    # Notes (MARC 593) - using custom description type
    note_593_fields = record_elem.findall('.//marc:datafield[@tag="593"]', MARC_NS)
    for note_field in note_593_fields:
        note_a = note_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if note_a is not None:
            additional_descriptions.append({
                'description': note_a.text.strip(),
                'type': {'id': 'notes', 'title': {'en': 'Notes'}}
            })
            record_additional_description_sources.append('593')

    # Data Availability Statement (MARC 594) - using custom description type
    note_594_fields = record_elem.findall('.//marc:datafield[@tag="594"]', MARC_NS)
    for note_field in note_594_fields:
        note_a = note_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if note_a is not None:
            additional_descriptions.append({
                'description': note_a.text.strip(),
                'type': {'id': 'data-availability', 'title': {'en': 'Data Availability Statement'}}
            })
            record_additional_description_sources.append('594')

    # Additional notes from MARC 904 - using custom description type
    note_904_fields = record_elem.findall('.//marc:datafield[@tag="904"]', MARC_NS)
    for note_field in note_904_fields:
        note_a = note_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if note_a is not None:
            additional_descriptions.append({
                'description': note_a.text.strip(),
                'type': {'id': 'notes', 'title': {'en': 'Notes'}}
            })
            record_additional_description_sources.append('904')

    # ==================== RIGHTS INFORMATION ====================

    rights = []

    # License (MARC 542$a) - Creative Commons license identifier
    rights_542 = record_elem.find('.//marc:datafield[@tag="542"]', MARC_NS)
    if rights_542 is not None:
        # License identifier (542$a)
        license_a = rights_542.find('.//marc:subfield[@code="a"]', MARC_NS)
        if license_a is not None:
            license_id = license_a.text.strip().upper()

            if license_id.lower() in LICENSE_MAPPINGS:
                # Use only id for known licenses
                rights.append({
                    'id': LICENSE_MAPPINGS[license_id.lower()]
                })
            else:
                # Use title for unknown licenses
                rights.append({'title': {'en': license_id}})

        # License description (542$f)
        license_f = rights_542.find('.//marc:subfield[@code="f"]', MARC_NS)
        if license_f is not None and license_a is None:
            rights_text = license_f.text.strip()

            if rights_text.lower() in LICENSE_MAPPINGS:
                # Use only id for known licenses
                rights.append({
                    'id': LICENSE_MAPPINGS[rights_text.lower()]
                })
            else:
                if not rights_text.lower().startswith('university of chicago dissertations are covered by copyright.')\
                        and not rights_text.lower().startswith('university of chicago theses are covered by copyright.'):
                    rights.append({'title': {'en': rights_text}})
                else:
                    metadata['copyright'] = strip_html_tags(rights_text)

    # Copyright statement (MARC 540)
    rights_540 = record_elem.find('.//marc:datafield[@tag="540"]', MARC_NS)
    if rights_540 is not None:
        # Copyright statement (540$a)
        copyright_a = rights_540.find('.//marc:subfield[@code="a"]', MARC_NS)
        if copyright_a is not None:
            copyright_text = copyright_a.text.strip()
            if copyright_text:
                metadata['copyright'] = strip_html_tags(copyright_text)

        # Skip 540$f as per CSV mapping (no longer used)

    # Distribution license (MARC 908) - generate URL
    distribution_license = record_elem.find('.//marc:datafield[@tag="908"]', MARC_NS)
    if distribution_license is not None:
        license_a = distribution_license.find('.//marc:subfield[@code="a"]', MARC_NS)
        if license_a is not None:
            license_text = license_a.text.strip()
            if license_text and license_text.lower() != 'i agree':
                # Generate distribution license URL as per CSV mapping
                dist_license_url = "https://knowledge.uchicago.edu/pages/?page=Distribution+License&ln=en"
                rights.append({
                    'identifier': dist_license_url,
                    'title': {'en': 'Distribution License'}
                })

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

            if scheme == 'url' and not idutils.is_url(identifier_text):
                scheme = 'other'

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
                if add_pages(resource_type, phys_text):
                    sizes.append(f"{phys_text} pages")
                else:
                    sizes.append(phys_text)

    if sizes:
        metadata['sizes'] = sizes

    # ==================== FORMATS ====================
    
    formats = []
    
    # Dataset format - human readable (MARC 337$a)
    format_337_fields = record_elem.findall('.//marc:datafield[@tag="337"]', MARC_NS)
    for format_field in format_337_fields:
        format_a = format_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if format_a is not None:
            formats.append(format_a.text.strip())

    # Format mimetype (MARC 347$b)
    format_347_fields = record_elem.findall('.//marc:datafield[@tag="347"]', MARC_NS)
    for format_field in format_347_fields:
        format_b = format_field.find('.//marc:subfield[@code="b"]', MARC_NS)
        if format_b is not None:
            formats.append(format_b.text.strip())

    if formats:
        metadata['formats'] = formats

    # Add additional descriptions to metadata if any exist
    if additional_descriptions:
        metadata['additional_descriptions'] = additional_descriptions

    # ==================== CUSTOM FIELDS ====================

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
        funder_name = funding_field.find('.//marc:subfield[@code="o"]', MARC_NS)

        # First check if there's a valid ROR ID in the funder identifier (536$q)
        funder_id_field = funding_field.find('.//marc:subfield[@code="q"]', MARC_NS)
        ror_id = None
        if funder_id_field is not None:
            original_id = funder_id_field.text.strip()
            ror_id = extract_ror_id_from_identifier(original_id)
            logger.debug(f"Funder ID processing: '{original_id}' -> '{ror_id}'")

        # Award number
        award_number = funding_field.find('.//marc:subfield[@code="1"]', MARC_NS)
        if award_number is not None:
            funding_info['award'] = {'number': award_number.text.strip()}

        # Award identifier (536$c) - write to file but don't add to metadata
        award_id = funding_field.find('.//marc:subfield[@code="c"]', MARC_NS)
        if award_id is not None:
            # Write award ID to awards.txt file for later processing
            award_id_text = award_id.text.strip()
            with open('awards.txt', 'a') as f:
                f.write(f"{record_identifier}, {award_id_text}\n")
            logger.debug(f"Logged award ID to awards.txt: {award_id_text}")
            # Note: Not adding award to funding_info to avoid validation errors

        # Award title
        award_title = funding_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if award_title is not None:
            if 'award' not in funding_info:
                funding_info['award'] = {}
            funding_info['award']['title'] = {'en': award_title.text.strip()}
        elif award_id is not None:
            # Award id as fallback title if title is absent
            if 'award' not in funding_info:
                funding_info['award'] = {}
            funding_info['award']['title'] = {'en': award_id.text.strip()}

        # Funder identifier - use the validated ROR ID as vocabulary reference
        if ror_id:
            # Use only the ROR ID when available (omit name to avoid vocabulary conflicts)
            funding_info['funder'] = {'id': ror_id}
            logger.debug(f"Setting funder ID to: '{ror_id}'")
        elif funder_name is not None:
            # Fall back to funder name only when no ROR ID is available
            funding_info['funder'] = {'name': funder_name.text.strip()}
            logger.debug(f"Setting funder name to: '{funder_name.text.strip()}'")
        elif 'award' in funding_info:
            # If we have award info but no funder, use unknown funder
            funding_info['funder'] = {'name': 'Unknown funder'}
            logger.debug("No funder info available, using 'Unknown funder'")

        # Only add to funding list if we have a funder (required field)
        if 'funder' in funding_info:
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

        # Meeting organizer
        meeting_organizer = meeting_field.find('.//marc:subfield[@code="u"]', MARC_NS)
        if meeting_organizer is not None:
            meeting_info['organizer'] = meeting_organizer.text.strip()

        if meeting_info:
            custom_fields['meeting'] = meeting_info

    # Division information (MARC 690)
    division_fields = record_elem.findall('.//marc:datafield[@tag="690"]', MARC_NS)
    divisions = []
    for division_field in division_fields:
        division_a = division_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if division_a is not None and division_a.text:
            # Convert text to vocabulary ID format using slugify
            division_id = slugify(division_a.text.strip())
            divisions.append({"id": division_id})

    if divisions:
        custom_fields['chicago:division'] = divisions

    # Center or Institute information (MARC 692)
    center_fields = record_elem.findall('.//marc:datafield[@tag="692"]', MARC_NS)
    centers_insts = []
    for center_field in center_fields:
        center_a = center_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if center_a is not None:
            # Convert to vocabulary ID format using slugify
            centers_insts.append({"id": slugify(center_a.text.strip())})

    if centers_insts:
        custom_fields['chicago:center_or_institute'] = centers_insts

    # Original submitter information (MARC 270)
    submitter_field = record_elem.find('.//marc:datafield[@tag="270"]', MARC_NS)
    if submitter_field is not None:
        submitter_email = submitter_field.find('.//marc:subfield[@code="m"]', MARC_NS)
        if submitter_email is not None:
            custom_fields['chicago:original_submitter'] = submitter_email.text.strip()

    # Journal information (MARC 773) and other journal fields
    journal_info = {}
    
    # Get journal title from MARC 773$t (canonical as per CSV)
    journal_field = record_elem.find('.//marc:datafield[@tag="773"]', MARC_NS)
    if journal_field is not None:
        # Journal title - prefer $t over $a
        journal_title_t = journal_field.find('.//marc:subfield[@code="t"]', MARC_NS)
        journal_title_a = journal_field.find('.//marc:subfield[@code="a"]', MARC_NS)

        if journal_title_t is not None:
            journal_info['title'] = journal_title_t.text.strip()
        elif journal_title_a is not None:
            # Skip $a if $t exists as per CSV mapping notes
            pass

        # Journal volume
        journal_volume = journal_field.find('.//marc:subfield[@code="j"]', MARC_NS)
        if journal_volume is not None:
            journal_info['volume'] = journal_volume.text.strip()

        # Journal issue
        journal_issue = journal_field.find('.//marc:subfield[@code="k"]', MARC_NS)
        if journal_issue is not None:
            journal_info['issue'] = journal_issue.text.strip()

        # Journal ISSN (773$x)
        journal_issn = journal_field.find('.//marc:subfield[@code="x"]', MARC_NS)
        if journal_issn is not None:
            journal_info['issn'] = journal_issn.text.strip()

    # Series statement (MARC 490$a) - maps to journal title
    series_field = record_elem.find('.//marc:datafield[@tag="490"]', MARC_NS)
    if series_field is not None and 'title' not in journal_info:
        series_a = series_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if series_a is not None:
            journal_info['title'] = series_a.text.strip()

    if journal_info:
        custom_fields['journal:journal'] = journal_info

    # Imprint information for books
    imprint_info = {}
    
    # Additional physical form (MARC 776$t)
    imprint_field = record_elem.find('.//marc:datafield[@tag="776"]', MARC_NS)
    if imprint_field is not None:
        imprint_t = imprint_field.find('.//marc:subfield[@code="t"]', MARC_NS)
        if imprint_t is not None:
            imprint_info['title'] = imprint_t.text.strip()

    # ISBN for books (MARC 020$a) - add to custom fields
    resource_type_id = resource_type.get('id', '')
    if resource_type_id in ['publication-book', 'publication-section']:
        isbn_field = record_elem.find('.//marc:datafield[@tag="020"]', MARC_NS)
        if isbn_field is not None:
            isbn_a = isbn_field.find('.//marc:subfield[@code="a"]', MARC_NS)
            if isbn_a is not None:
                isbn_text = isbn_a.text.strip().split()[0]  # Clean ISBN
                imprint_info['isbn'] = isbn_text

    if imprint_info:
        custom_fields['imprint:imprint'] = imprint_info

    # Related Item information (MARC 791)
    related_item_fields = record_elem.findall('.//marc:datafield[@tag="791"]', MARC_NS)
    related_items = []
    
    for related_field in related_item_fields:
        related_item = {}
        
        # Related Item Identifier Type (791$2)
        id_type = related_field.find('.//marc:subfield[@code="2"]', MARC_NS)
        if id_type is not None:
            related_item['identifier'] = {'scheme': id_type.text.strip()}
        
        # Related Item Type (791$a)
        item_type = related_field.find('.//marc:subfield[@code="a"]', MARC_NS)
        if item_type is not None:
            related_item['item_type'] = item_type.text.strip()
        
        # Relation Type (791$e)
        relation_type = related_field.find('.//marc:subfield[@code="e"]', MARC_NS)
        if relation_type is not None:
            related_item['relation_type'] = relation_type.text.strip()
        
        # Related Item Title (791$t)
        related_title = related_field.find('.//marc:subfield[@code="t"]', MARC_NS)
        if related_title is not None:
            related_item['title'] = related_title.text.strip()
        
        # Related Item Identifier (791$w)
        related_identifier = related_field.find('.//marc:subfield[@code="w"]', MARC_NS)
        if related_identifier is not None:
            if 'identifier' not in related_item:
                related_item['identifier'] = {}
            related_item['identifier']['identifier'] = related_identifier.text.strip()
        
        if related_item:
            related_items.append(related_item)
    
    if related_items:
        custom_fields['chicago:related_items'] = related_items

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
        coord_b = geo_field.find('.//marc:subfield[@code="b"]', MARC_NS)  # latitude for point (-118.1)
        coord_c = geo_field.find('.//marc:subfield[@code="c"]', MARC_NS)  # longitude for point (34.1)
        coord_d = geo_field.find('.//marc:subfield[@code="d"]', MARC_NS)  # coord1 for polygon (-104.05)
        coord_e = geo_field.find('.//marc:subfield[@code="e"]', MARC_NS)  # coord2 for polygon (-111.05)
        coord_f = geo_field.find('.//marc:subfield[@code="f"]', MARC_NS)  # coord3 for polygon (45.01)
        coord_g = geo_field.find('.//marc:subfield[@code="g"]', MARC_NS)  # coord4 for polygon (40.99)

        feature = {}

        if place_a is not None:
            feature['place'] = place_a.text.strip()

        # Check if we have point coordinates (lat/lng)
        if coord_b is not None and coord_c is not None:
            try:
                # Based on CSV mapping: 975$b = coordinates[1] (latitude), 975$c = coordinates[0] (longitude)
                lat = float(coord_c.text.strip())  # 975$c is latitude
                lng = float(coord_b.text.strip())  # 975$b is longitude
                feature['geometry'] = {
                    'type': 'Point',
                    'coordinates': [lng, lat]  # GeoJSON format: [longitude, latitude]
                }
            except ValueError:
                logger.warning(f"Invalid coordinates in MARC 975: lat={coord_c.text}, lng={coord_b.text}")

        # Check if we have polygon coordinates (bounding box)
        elif all(coord is not None for coord in [coord_d, coord_e, coord_f, coord_g]):
            try:
                # Based on CSV mapping: 975$d = coordinates[0], 975$e = coordinates[1], 975$f = coordinates[2], 975$g = coordinates[3]
                coord1 = float(coord_d.text.strip())  # -104.05
                coord2 = float(coord_e.text.strip())  # -111.05  
                coord3 = float(coord_f.text.strip())  # 45.01
                coord4 = float(coord_g.text.strip())  # 40.99

                # Create bounding box polygon: [west, south, east, north]
                west = min(coord1, coord2)
                east = max(coord1, coord2)
                south = min(coord3, coord4)
                north = max(coord3, coord4)

                feature['geometry'] = {
                    'type': 'Polygon',
                    'coordinates': [[
                        [west, south],   # southwest
                        [east, south],   # southeast
                        [east, north],   # northeast
                        [west, north],   # northwest
                        [west, south]    # close polygon
                    ]]
                }
            except ValueError:
                logger.warning(f"Invalid polygon coordinates in MARC 975")

        if feature:
            locations.append({'features': [feature]})

    if locations:
        metadata['locations'] = locations


    record = {
        'pids': pids,
        'metadata': metadata,
        'files': {'enabled': True},
        'access': {
            'record': 'public',
            'files': 'public'
        }
    }

    if internal_notes:
        record['internal_notes'] = internal_notes

    # ==================== ACCESS RIGHTS ====================

    # Check for embargo information (MARC 856$e)
    embargo_fields = record_elem.findall('.//marc:datafield[@tag="856"][@ind1="4"]', MARC_NS)
    for embargo_field in embargo_fields:
        embargo_e = embargo_field.find('.//marc:subfield[@code="e"]', MARC_NS)
        if embargo_e is not None:
            embargo_text = embargo_e.text.strip().lower()
            if 'restricted' in embargo_text:
                record['access']['record'] = 'restricted'
                record['access']['files'] = 'restricted'

            elif 'embargo' in embargo_text:
                date_obj = None
                try:
                    date_obj = datetime.strptime(embargo_text[9:-1], '%Y-%m-%d')
                except Exception:
                    continue

                if date_obj:
                    active = date_obj > datetime.now()

                    record['access']['embargo'] = {
                        'active': active,
                        'until': str(date_obj.date())
                    }

                    if active:
                        record['access']['record'] = 'restricted'
                        record['access']['files'] = 'restricted'

                else:
                    record['access']['embargo'] = {'active': False}

    if custom_fields:
        record['custom_fields'] = custom_fields

    return record, file_information


def add_files_to_draft(draft: RecordItem, identity, filepath: str, file_information):
    """Add files to the draft record.

    Args:
        draft: The draft record
        identity: User identity for authentication
        filepath: Root filepath for associated files
        file_information: Additional file information to match file descriptions
    """
    try:
        # Path to the record's file/s 'chicago:tind_id'
        record_file_path = os.path.join(filepath, str(draft.data.get("custom_fields", {}).get("chicago:tind_id", "")))

        # Check if file\s exists
        if not os.path.exists(record_file_path):
            logger.warning(f"Directory not found at {record_file_path}, skipping file upload")
            return

        # Get the draft files service
        draft_file_service = current_rdm_records_service.draft_files

        # Initialize file metadata
        file_names = os.listdir(record_file_path)
        file_data = [{"key": file_name} for file_name in file_names]

        logger.info(f"Processing {len(file_names)} files for draft {draft.id}")
        logger.info(f"File information available: {file_information}")

        draft_file_service.init_files(identity, draft.id, data=file_data)

        for file_name in file_names:
            # Upload file content
            with open(os.path.join(record_file_path, file_name), "rb") as f:
                draft_file_service.set_file_content(identity, draft.id, file_name, f)

            # Commit the file
            draft_file_service.commit_file(identity, draft.id, file_name)

            # Update file metadata if description is available
            match = next((info for info in file_information if info.get('url') == file_name), None)
            if match:
                # Try wrapping in metadata key
                data = {'metadata': {'description': match['description']}}
                logger.info(f"Attempting to update metadata for file {file_name} with data: {data}")
                try:
                    draft_file_service.update_file_metadata(identity, draft.id, file_name, data)
                    logger.info(f"Successfully updated metadata for file {file_name}")
                except Exception as e:
                    logger.error(f"Failed to update metadata for {file_name}: {e}")
            else:
                logger.info(f"No description found for file {file_name}")

        logger.info(f"Successfully uploaded {len(file_names)} files to draft {draft.id}")

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


def get_default_preview(file_information: list) -> str:
    """Get the default preview file from file information.

    Most common 856$y combinations:
    ----------------------------------------
    1463 records: Article | Supporting information
    616 records: Approval Form | Dissertation
    255 records: Article | Supplementary materials
    185 records: Approval | Thesis
    149 records: Article | Supplemental material
    147 records: Article | Supplementary material
    135 records: Article | Supplementary information
    135 records: Article | Supplemental files
    113 records: Additional files | Article
    89 records: Article | Supplementary data


    Args:
        file_information: List of file information dictionaries

    Returns:
        Filename of the default preview file or empty string
    """
    for file_info in file_information:
        if file_info.get('description', '').lower() in ['article', 'dissertation', 'thesis']:
            return file_info.get('url', '')

    # Fallback: first non-license file
    for file_info in [f for f in file_information if 'license' not in f.get('url', '').lower()]:
        return file_info.get('url', '')

    return ''


def process_records_batch(records_batch, identity, community_map: dict, file_path: str, community_algorithm=None) -> list:
    """Process a batch of records.

    Args:
        records_batch: List of XML record elements
        identity: ID of the record owner
        community_map: Mapping of community slugs to IDs
        file_path: Root filepath for associated files
        community_algorithm: Community assignment algorithm instance

    Returns:
        List of created record IDs
    """
    global errors_log
    global warnings_log
    results = []

    for record_elem in records_batch:
        invenio_data = None
        record_identifier = "Unknown"
        error_record = {
            "record_identifier": record_identifier,
            "error_stage": None,
            "error_message": None,
            "error_details": None,
            "invenio_data": None,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        
        try:
            # Extract record identifier for error tracking
            control_001 = record_elem.find('.//marc:controlfield[@tag="001"]', MARC_NS)
            if control_001 is not None:
                record_identifier = control_001.text.strip()
                error_record["record_identifier"] = record_identifier
            
            # Convert MARC to InvenioRDM format
            invenio_data, file_information = parse_marc_record(record_elem, record_identifier)
            error_record["invenio_data"] = invenio_data

            record_file_path = os.path.join(file_path, record_identifier)
            add_files = True

            if not os.path.exists(record_file_path):
                invenio_data['files'] = {'enabled': False}
                add_files = False
            
            # Extract DOI for better identification
            if 'identifiers' in invenio_data.get('metadata', {}):
                for identifier in invenio_data['metadata']['identifiers']:
                    if identifier.get('scheme') == 'doi':
                        record_identifier = identifier['identifier']
                        error_record["record_identifier"] = record_identifier
                        break

            # Create draft record
            error_record["error_stage"] = "create_draft"
            draft = current_rdm_records_service.create(
                data=invenio_data,
                identity=identity
            )

            # Check if draft creation was successful
            if draft is None:
                raise ValueError("Draft record creation failed - service returned None")

            # Add files to the draft
            if add_files:
                error_record["error_stage"] = "add_files"
                add_files_to_draft(draft, identity, file_path, file_information)

                # Set default preview after files are uploaded and committed
                default_preview = get_default_preview(file_information)
                if default_preview:
                    error_record["error_stage"] = "set_default_preview"
                    invenio_data['files']['default_preview'] = default_preview
                    current_rdm_records_service.update_draft(
                        identity=identity,
                        id_=draft.id,
                        data=invenio_data
                    )

            # Publish the record
            error_record["error_stage"] = "publish"
            published = current_rdm_records_service.publish(
                id_=draft.id,
                identity=identity
            )
            
            # Check if publishing was successful
            if published is None:
                raise ValueError("Record publishing failed - service returned None")


            # Use community assignment algorithm to assign ALL possible communities
            if community_algorithm:
                
                # Extract field values from the record
                custom_fields = invenio_data.get('custom_fields', {})
                divisions_raw = custom_fields.get('chicago:division', [])
                departments = custom_fields.get('chicago:department', [])
                centers = custom_fields.get('chicago:center_or_institute', [])
                resource_type = invenio_data.get('metadata', {}).get('resource_type', {}).get('id', '')

                # Handle VocabularyCF format: [{"id": ".."}] -> extract IDs
                # The algorithm CSV uses original text, so we need to convert IDs back
                # For now, extract the 'id' values (algorithm will need updating to match)
                def extract_values(field_data):
                    """Extract values from field data, handling both old and new formats."""
                    if not field_data:
                        return []
                    if isinstance(field_data, str):
                        return [field_data]
                    result = []
                    for item in field_data:
                        if isinstance(item, dict) and 'id' in item:
                            result.append(item['id'])
                        elif isinstance(item, str):
                            result.append(item)
                    return result

                divisions = extract_values(divisions_raw)
                departments = extract_values(departments)
                centers = extract_values(centers)
                
                # Get community assignments
                assignment_result = community_algorithm.assign_communities(
                    divisions=divisions,
                    departments=departments,
                    centers=centers,
                    resource_type=resource_type
                )
                
                # Debug logging for community assignment
                logger.info(f"Record {published.id} field values: divisions={divisions}, departments={departments}, centers={centers}, resource_type={resource_type}")
                logger.info(f"Algorithm returned {len(assignment_result.get('communities', []))} communities: {assignment_result.get('communities', [])}")
                
                # Add record to ALL assigned communities
                if assignment_result.get('communities'):
                    for community_name in assignment_result['communities']:
                        # Map community name to community ID
                        logger.info(f"Looking up community '{community_name}' in community_map")
                        if community_name in community_map:
                            community_id = community_map[community_name]
                            logger.info(f"Found community '{community_name}' with ID {community_id}")
                            
                            try:
                                request_id = current_record_communities_service.add(
                                    identity,
                                    published.id,
                                    dict(communities=[dict(id=community_id, require_review=False)]),
                                )[0][0]["request_id"]

                                current_requests_service.execute_action(
                                    identity, request_id, "accept"
                                )
                                
                                logger.info(f"Added record {published.id} to community '{community_name}' (ID: {community_id})")
                                
                            except Exception as community_error:
                                logger.warning(f"Failed to add record {published.id} to community '{community_name}': {community_error}")
                        else:
                            logger.warning(f"Community '{community_name}' not found in community_map")
                    
                    # Log assignment details
                    logger.info(f"Record {published.id} assigned to {len(assignment_result['communities'])} communities using method '{assignment_result['method']}'")
                else:
                    logger.info(f"No communities assigned for record {published.id}: {assignment_result.get('method', 'unknown method')}")
            else:
                logger.debug(f"Community algorithm not available for record {published.id} - skipping community assignment")

            results.append(published.id)

        except Exception as e:
            error_record["error_message"] = str(e)
            error_record["error_details"] = {
                "exception_type": type(e).__name__,
                "exception_args": str(e.args) if hasattr(e, 'args') else None
            }
            
            # Try to extract more detailed error information
            if hasattr(e, 'messages'):
                error_record["error_details"]["validation_errors"] = e.messages
            elif hasattr(e, 'errors'):
                error_record["error_details"]["validation_errors"] = e.errors
            elif hasattr(e, 'description'):
                error_record["error_details"]["description"] = e.description
            
            errors_log.append(error_record)
            logger.error(f"Error processing record {record_identifier} at stage {error_record['error_stage']}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            continue

    return results


@click.command("import_data")
@click.argument("email")
@click.argument("data")
@click.argument("file_path")
@click.option("--batch-size", default=500, help="Number of records to process in each batch")
@click.option("--max-records", default=3000, type=int, help="Maximum number of records to process (for testing)")
def import_data(email: str, data: str, file_path:str, batch_size: int, max_records: Optional[int]):
    """Import MARCXML bibliographic data into Chicago Invenio.

    Args:
        email: Email of the user who will own the records
        data: Path to the MARCXML file
        filepath: Root filepath for associated files, files will be looked for in subfolders named by record ID
                  if that subfolder does not exist, files will not be added to that record
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

        identity = get_identity_with_roles(owner)

        # Get create community collection structure and get community map
        community_map = get_create_community_collection_structure(identity)

        # Initialize community assignment algorithm
        try:
            community_algorithm = CommunityAssignmentAlgorithm(CSV)
            logger.info("Community assignment algorithm initialized successfully")
        except ImportError as e:
            logger.error(f"Could not import CommunityAssignmentAlgorithm: {e}")
            community_algorithm = None
        except Exception as e:
            logger.error(f"Failed to initialize community assignment algorithm: {e}")
            community_algorithm = None

        # Clear the global error log at the start of each import
        global errors_log
        errors_log = []
        
        # Clear the awards.txt file at the start of import
        with open('awards.txt', 'w') as f:
            f.write("")  # Clear file
        
        logger.info(f"Starting XML import for user: {email}")
        logger.info(f"Data file: {data}")
        logger.info(f"File path: {file_path}")
        logger.info(f"Batch size: {batch_size}")
        logger.info(f"Awards will be logged to awards.txt")

        start_time = time.time()
        total_processed = 0
        total_created = 0

        try:
            # Stream records from XML file
            record_stream = stream_marc_records(data)

            # Process records in batches
            while True:
                batch = list(islice(record_stream, batch_size))
                if not batch:
                    break

                # Check max_records limit
                if max_records and total_processed >= max_records:
                    logger.info(f"Reached maximum records limit: {max_records}")
                    #break

                # Process the batch
                batch_results = process_records_batch(batch, identity, community_map, file_path, community_algorithm)

                total_processed += len(batch)
                total_created += len(batch_results)

                logger.info(
                    f"Batch complete: {len(batch)} processed, "
                    f"{len(batch_results)} created. "
                    f"Total: {total_processed} processed, {total_created} created"
                )

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

        logger.info("=" * 50)

        # Write errors to JSON file
        if errors_log:
            with open("errors.json", 'w', encoding='utf-8') as f:
                json.dump(errors_log, f, indent=2, ensure_ascii=False, default=str)
            logger.info(f"Wrote {len(errors_log)} errors to errors.json")
        else:
            logger.info("No errors to write - all records processed successfully!")

        if warnings_log:
            with open("warnings.json", 'w', encoding='utf-8') as f:
                json.dump(warnings_log, f, indent=2, ensure_ascii=False)
            logger.info(f"Wrote {len(warnings_log)} warnings to warnings.json")


if __name__ == "__main__":
    import_data()