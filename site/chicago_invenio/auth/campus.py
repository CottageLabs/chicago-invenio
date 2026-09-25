"""Campus-only access for users who logged in via University of Chicago SSO (CNET).

Users with a linked CNET identity get the ``campus_user`` need, which the record
permission policy uses to grant access to files that are restricted on otherwise
public records.
"""

from flask_login import current_user
from invenio_access.permissions import SystemRoleNeed
from invenio_accounts.models import UserIdentity
from invenio_records_permissions.generators import Generator

# External method recorded against a user's identity by the CNET SSO signup handler
CHI_SSO_METHOD = "chi_sso"

campus_user = SystemRoleNeed("campus_user")


def load_campus_user_on_identity_loaded(sender, identity):
    """Add the campus_user need to identities of users linked to CNET SSO."""
    if not current_user.is_authenticated:
        return

    has_sso_identity = (
        UserIdentity.query.filter_by(id_user=current_user.id, method=CHI_SSO_METHOD)
        .first()
        is not None
    )
    if has_sso_identity:
        identity.provides.add(campus_user)


class CampusUser(Generator):
    """Allows users who logged in via CNET SSO."""

    def needs(self, **kwargs):
        """Enabling needs."""
        return [campus_user]
