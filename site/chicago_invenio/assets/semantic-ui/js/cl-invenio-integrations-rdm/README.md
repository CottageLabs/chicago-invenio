# CL Toolkit Integrations | Invenio RDM Records
A submodule dedicated to implementing functionality needed for CL implementations of RDM records/deposits

## Implementation warnings
Some of the integrations are forced into less-than-perfect decisions because of upstream dependencies.
We demarcate those here so that we can track those in case of regressions or potentially commit upstream tweaks to make our lives (and hopefully the community's) easier.

## Transpilation
This is currently pretranspiled by webpack aliasing the code that _already_ exists in Chicago. Before publishing as a standalone NPM this needs to be babel transpiled.


## useDepositSubmit()
We are forced into an internal import of DepositFormSubmitContext as it is not available via ordinary export from the module.

## RDMHeaderSearchBarContainer
Invenio RDM mounts a standalone non SearchKit search bar into `#header-search-bar`. This is available on all pages and redirects to the search page with query `q=wibble`.

On SearchKit powered pages, a separate React application renders a Searchkit connected search bar into the same DOM element using a portal. This portal component clears the target node using `innerHTML=""`.

This is a brittle implementation detail, two React trees attempting to manage the same DOM node. Even worse, the destructive DOM change removes elements managed by React without informing React, and on every redraw, essentially removing itself. We encountered this in Chicago when opening the filter drawer on mobile caused the connected search input to disappear.

This integration attempts to work around that issue by using the existing `SearchApp.searchbarContainer` override to solve the conflict. It moves the `innerHTML=""` into a useEffect which fires exactly ONCE on mount, so any subsequent redraws do not cause the searchkit search to vanish. We continue to use `innerHTML=""` to keep implementation tweaks and details as close to upstream as possible, but it does not represent a "good" solution to the issue.

### Recommended upstream implementation

This integration is a _workaround_ and doesn't actually solve the issue at hand, which we believe is a shared concern that should be designed differently upstream. Being able to override the standalone search implementation as _well_ might allow an integration such as this to handle things in a slightly different way, so separate to any redesigns that would be a nice improvement to see.

There should be an upstream discussion about how InvenioRDM, and potentially Invenio as a whole ecosystem, manages its header search. Currently, the standalone search and Searchkit search are initialised independently, which is what leads to the competing React problem above.

One potential solution might be for RDM to initialise a Searchkit header search for the main page, not just search. Alternatively RDM could explicitly determine which implementation owns the header before mounting anything.

In either of those solutions though, we think Invenio Search UI should avoid destructive `innerHTML=""` mutations and document the expectation that portal targets must not already contain DOM managed by another React root.

