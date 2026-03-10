import html
import re
import unicodedata

from flask_principal import Identity, RoleNeed, UserNeed
from invenio_access.permissions import any_user, authenticated_user


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