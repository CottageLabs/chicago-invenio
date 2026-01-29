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
        ),
    },
)
