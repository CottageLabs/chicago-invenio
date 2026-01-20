from invenio_rdm_records.requests import CommunitySubmission
from invenio_rdm_records.services.permissions import RDMRequestsPermissionPolicy
from invenio_requests.services.generators import Creator, Receiver

from invenio_curations.requests.curation import CurationRequest
from invenio_curations.services.generators import (
    IfCurationRequestAccepted,
    IfRequestTypes,
    TopicPermission,
)


class CurationRDMRequestsPermissionPolicy(RDMRequestsPermissionPolicy):
    """Customized permission policy for sane handling of curation requests."""

    curation_request_record_review = IfRequestTypes(
        [CurationRequest],
        then_=[TopicPermission(permission_name="can_review")],
        else_=[],
    )

    # Only allow community-submission requests to be accepted after the rdm-curation request has been accepted
    can_action_accept = [
        IfRequestTypes(
            request_types=[CommunitySubmission],
            then_=[
                IfCurationRequestAccepted(
                    then_=RDMRequestsPermissionPolicy.can_action_accept, else_=[]
                )
            ],
            else_=RDMRequestsPermissionPolicy.can_action_accept,
        )
    ]

    # Update can read and can comment with new states
    can_read = [
        # Have to explicitly check the request type and circumvent using status, as creator/receiver will add a query filter where one entity must be the user.
        IfRequestTypes(
            [CurationRequest],
            then_=[
                Creator(),
                Receiver(),
                TopicPermission(permission_name="can_review"),
            ],
            else_=RDMRequestsPermissionPolicy.can_read,
        )
    ]

    can_create_comment = can_read

    # Update submit to also allow record reviewers/managers for curation requests
    can_action_submit = RDMRequestsPermissionPolicy.can_action_submit + [
        curation_request_record_review
    ]
    # Add new actions
    can_action_review = RDMRequestsPermissionPolicy.can_action_accept
    can_action_critique = RDMRequestsPermissionPolicy.can_action_accept

    can_action_resubmit = can_action_submit
