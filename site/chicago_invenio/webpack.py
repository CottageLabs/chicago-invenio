"""JS/CSS Webpack bundles for Chicago Invenio."""

from invenio_assets.webpack import WebpackThemeBundle

# TODO toolkit config requires several extra functions and things atm,
#  should be a way to extend invenio itself with a pyton lib maybe to avoid repeating all this

  # ---------- POTENTIAL IDEA ----------
  # Expose the versions of modules we're using with invenio_rdm
  # so that any integrations can be VERSIONED and we can head off breaking changes
  #
  # Idea is that let's say invenio_curations changes internal stuff breaking our integration on 0.6.5,
  # and we're on @cottagelabs/invenio_integrations_curations:1.2.1. Then we release 1.2.2 with an EXPLICIT
  # build failure for any version over 0.6.4 of curations.
  # We THEN release @cottagelabs/invenio_integrations_curations:2.0.0 with an EXPLICIT build failure
  # for any curations release < 0.6.5.
  #
  # This way we get prior warning before upgrading, and can upgrade multiple instances with custom curations
  # frontend code much much easier, even across breaking changes.
  #
  # We build this in with an invenio_compatibilities built into the frontend npm package, then validate it at bundle time

from pathlib import Path
from .toolkit_config import validate_toolkit

CURATIONS_TOOLKIT_DIR = (
    Path(__file__).resolve().parent
    / "assets"
    / "semantic-ui"
    / "js"
    / "cl-invenio-integrations-curations"
)

RDM_TOOLKIT_DIR = (
    Path(__file__).resolve().parent
    / "assets"
    / "semantic-ui"
    / "js"
    / "cl-invenio-integrations-rdm"
)

validate_toolkit(CURATIONS_TOOLKIT_DIR)
validate_toolkit(RDM_TOOLKIT_DIR)

theme = WebpackThemeBundle(
    __name__,
    "assets",
    default="semantic-ui",
    themes={
        "semantic-ui": dict(
            entry={
                "chicago-communities-frontpage": "./js/chicago_invenio/communities/frontpage.js",
            },
            dependencies={
                "@cottagelabs/invenio-integrations-rdm":
                    "file:./js/cl-invenio-integrations-rdm",
                "@cottagelabs/invenio-integrations-curations":
                    "file:./js/cl-invenio-integrations-curations",

                "@tanstack/react-query": "^4.44.0",
                "react-invenio-forms": "^4.0.0",
                "semantic-ui-react": "^2.1.0",
            }
        ),
    },
)
