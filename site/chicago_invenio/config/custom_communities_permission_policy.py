# site/yourmodule/permissions.py

from flask import current_app
from flask_principal import RoleNeed
from invenio_administration.generators import Administration
from invenio_communities.permissions import CommunityPermissionPolicy
from invenio_records_permissions.generators import Generator, SystemProcess

class CommunityCreator(Generator):
    """Grant permissions to custom community-creator role"""
    def needs(self, record=None, **kwargs):
        role_name = current_app.config.get(
            "COMMUNITY_CREATOR_ROLE", "community-creator"
        )
        return [RoleNeed(role_name)]


class CustomCommunitiesPermissionPolicy(CommunityPermissionPolicy):
    """
    Custom permission policy for communities.

    This class overrides the default `CommunityPermissionPolicy` to provide
    a tailored permission model for community-related actions.

    This policy demonstrates how to grant specific permissions for community creation actions:

    - Community creation (`can_create`) is allowed for:
        - Users with the custom 'community-creator' role
        - Users with administration role
        - System processes

    - Direct inclusion of records (`can_include_directly`) is allowed for:
        - Users with administration role
        - System processes
    """
    can_create = [CommunityCreator(), Administration(), SystemProcess()]
    can_include_directly = [Administration(), SystemProcess()]
