import html
import re
import unicodedata

from flask_principal import Identity, RoleNeed, UserNeed
from invenio_access.permissions import any_user, authenticated_user

MARC_NS = {'marc': 'http://www.loc.gov/MARC21/slim'}


def slugify(text):
    """Convert text to slug format (same as load_as_coms_colls.py)."""
    text = unicodedata.normalize('NFKD', text)
    text = text.encode('ascii', 'ignore').decode('ascii')
    # remove punctuation (keep letters, numbers, whitespace and hyphens)
    text = re.sub(r'[^\w\s-]', '', text)
    # replace whitespace/underscores with hyphens and collapse consecutive hyphens
    text = re.sub(r'[\s_]+', '-', text.strip().lower())
    return text.strip('-')


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


def has_mixed_restricted_files(elem) -> bool:
    fields = elem.findall(f'.//marc:datafield[@tag="856"]', MARC_NS)

    if len(fields) > 1:
        access_restrictions = []

        for field in fields:
            subfields = field.findall('.//marc:subfield', MARC_NS)

            for subfield in subfields:
                code = subfield.get('code', 'unknown')
                if code == 'e':
                    access_restrictions.append(subfield.text.strip().lower())

        if 'public' in access_restrictions:
            if 'restricted' in access_restrictions:
                return True
            elif 'restricted_admin' in access_restrictions:
                return True
            elif any([acces_res.startswith('embargo') for acces_res in access_restrictions]):
                return True
        elif any([acces_res.startswith('embargo') for acces_res in access_restrictions]):
            if 'restricted' in access_restrictions:
                return True
            elif 'restricted_admin' in access_restrictions:
                return True

    return False