"""Chicago Invenio Flask extension."""

from flask_principal import identity_loaded

from chicago_invenio.auth.campus import load_campus_user_on_identity_loaded


class ChicagoInvenio:
    """Chicago Invenio extension, loaded in both the UI and API apps."""

    def __init__(self, app=None):
        """Extension initialization."""
        if app:
            self.init_app(app)

    def init_app(self, app):
        """Flask application initialization."""
        identity_loaded.connect_via(app)(load_campus_user_on_identity_loaded)
        app.extensions["chicago-invenio"] = self
