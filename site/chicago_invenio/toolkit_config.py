from importlib.metadata import PackageNotFoundError, version

import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from packaging.specifiers import SpecifierSet
from packaging.version import Version


## TODO ALL of this should probably go in a @cottagelabs/invenio_python_toolkit py lib or something?

def get_package_version(package_name):
    try:
        return version(package_name)
    except PackageNotFoundError:
        return None


def package_versions():
    """Expose installed backend package versions to Jinja."""
    return {
        "backend_versions": {
          "invenio_communities": get_package_version("invenio_communities"),
          "invenio_curations": get_package_version("invenio_curations"),
          "invenio_rdm_records": get_package_version("invenio_rdm_records"),
          "invenio_app_rdm": get_package_version("invenio_app_rdm"),
        }
    }



def validate_toolkit(toolkit_dir: Path):
    package = json.loads(
        (toolkit_dir / "package.json").read_text()
    )

    toolkit_name = package["name"]
    toolkit_version = Version(package["version"])

    for dependency, rules in package.get(
        "invenioCompatibility", {}
    ).items():
        try:
            installed = Version(version(dependency))
        except PackageNotFoundError:
            raise RuntimeError(
                f"{toolkit_name}: missing Python package {dependency}"
            ) from None

        matching_rules = [
            rule for rule in rules
            if installed in SpecifierSet(rule["backend"])
        ]

        if len(matching_rules) > 1:
            raise RuntimeError(
                f"Ambiguous compatibility rules for "
                f"{dependency}=={installed}"
            )

        if not matching_rules:
            raise RuntimeError(
                f"\nINCOMPATIBLE INVENIO INTEGRATION\n"
                f"No declared compatibility for {dependency}=={installed}\n"
                f"Toolkit: {toolkit_name}@{toolkit_version}\n"
                f"Build aborted."
            )

        required_toolkit = matching_rules[0]["toolkit"]

        if toolkit_version not in SpecifierSet(required_toolkit):
            raise RuntimeError(
                f"\nINCOMPATIBLE INVENIO INTEGRATION\n"
                f"Backend: {dependency}=={installed}\n"
                f"Toolkit: {toolkit_name}@{toolkit_version}\n"
                f"Compatible toolkit versions: {required_toolkit}\n"
                f"Build aborted."
            )