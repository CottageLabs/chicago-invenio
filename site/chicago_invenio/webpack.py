"""JS/CSS Webpack bundles for Chicago Invenio."""

from invenio_assets.webpack import WebpackThemeBundle

theme = WebpackThemeBundle(
    __name__,
    "assets",
    default="semantic-ui",
    themes={
        "semantic-ui": dict(
            entry={
                "chicago-communities-frontpage": "./js/chicago_invenio/communities/frontpage.js",
            },
            # These should be published probably as an NPM, but we need to know how that handles the @js stuff
            aliases={
                "@cl-toolkit": "./js/cl-invenio-frontend-toolkit",
            },
            dependencies={
                "@tanstack/react-query": "^4.44.0",
                "react-invenio-forms": "^4.0.0",
                "semantic-ui-react": "^2.1.0",
            }
        ),
    },
)
