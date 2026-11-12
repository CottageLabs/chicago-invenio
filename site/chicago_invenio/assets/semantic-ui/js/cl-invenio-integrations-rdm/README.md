# CottageLabs Invenio Integrations | RDM

This is the RDM flavour CottageLabs integration library.

## Design
Invenio modules/extensions, particularly those affecting the DepositForm, seem to quite often make assumptions that they will be the top user layer.
This is fine if:
- There are no customisations required
- The implementation does not require MULTIPLE of these extensions, which may not play nicely together.

If either of these are not the case, then an individual instance of invenio may need extensive and brittle custom code to perform as expected.
In some cases, this code is forced to rely on internal implementation choices, not exposed via a public interface.
That can (and likely will) lead to a situation where a patch or minor change for one of those customisations breaks the UI for a customer in an unexpected way.
In the worst case scenario it might then require debugging and changing behaviour in multiple different ways across multiple different customer codebases.

The proposed solution is these integration NPMs. They aim to centralise any brittle internals into a single place with a stable interface.
Should an underlying dependency make implementation changes that break things, these libraries can reflect that as a breaking change instead and enforce versioning at build time.
They can also attempt to keep behaviour of exported hooks/components consistent, allowing work to be done once and customisations to simply pull in updates.


## Versioning and upstream compatibility

Each integration is versioned independently using semantic versioning. The `invenioCompatibility` field in `package.json` declares which versions of the upstream Python packages it supports.

Because some integrations depend on internal Invenio code rather than public APIs, upstream changes can break things without a major version bump. We deliberately restrict supported versions so builds fail early rather than allowing potentially broken integrations through.

When upstream releases a new version:

- **If it's compatible**, verify it and release a patch (e.g. `1.0.1`) extending the supported version range.
- **If it breaks the integration**, release a patch (e.g. `1.0.2`) restricting the existing range and documenting which toolkit version will support the new upstream release.
- **If fixes are needed**, release an updated integration. Use a major version (e.g. `2.0.0`) if the integration's public API or supported compatibility contract needs to change. Otherwise, a patch or minor release may be enough.

For example, if `invenio-rdm-records 21.3.4` breaks an integration previously supporting all of `21.x`, we can restrict toolkit `1.x` to `<21.3.4` and release toolkit `2.x` with the required changes.

Existing releases won't automatically pick up new compatibility rules, so consumers must update their integration packages to benefit from these checks, which is why it is recommended to ALWAYS use caret dependencies for this integration toolkit.

The aim is to catch upstream incompatibilities during the build and handle them in one place, rather than discovering and fixing the same problems separately in each client implementation.