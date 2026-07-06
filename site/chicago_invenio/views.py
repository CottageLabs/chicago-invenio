"""Additional views."""

from flask import Blueprint, abort, current_app, g, redirect, url_for
from invenio_rdm_records.proxies import current_rdm_records_service


#
# Registration
#
def create_blueprint(app):
    """Register blueprint routes on app."""
    blueprint = Blueprint(
        "chicago_invenio",
        __name__,
        template_folder="./templates",
    )

    # Legacy TIND record URLs (e.g. https://knowledge.uchicago.edu/record/16964)
    # are redirected to the matching Invenio RDM record.
    blueprint.add_url_rule(
        "/record/<int:tind_id>",
        view_func=redirect_to_tind_record,
    )

    return blueprint


def redirect_to_tind_record(tind_id):
    """Redirect a legacy TIND record URL to the corresponding Invenio record.

    Looks up the record whose "chicago:tind_id" custom field matches the
    given TIND id, and redirects to that record's landing page.
    """
    query = rf"custom_fields.chicago\:tind_id:{tind_id}"

    try:
        results = current_rdm_records_service.search(
            identity=g.identity, params={"q": query, "size": 1}
        )
    except Exception as e:
        current_app.logger.exception(
            "Unknown error occurred while searching for TIND id.", extra={"error": e}
        )
        abort(500)

    hits = list(results.hits)
    if not hits:
        abort(404)

    return redirect(
        url_for("invenio_app_rdm_records.record_detail", pid_value=hits[0]["id"]),
        code=301,
    )
