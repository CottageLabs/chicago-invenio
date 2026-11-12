# Suggestions for future guidelines

These are some possible guidelines  for improving frontend development across the Invenio ecosystem (initially focused on RDM and its extensions). These are not intended as a comprehensive list of requirements, and more thoughts have gone into some areas than others.

I'd like this (and the other two documents) to be a starting point for community discussion around these topics. I don't want to impose an iron will declaration of what it means to be a good Invenio citizen, rather start from "as a frontend developer, what would I like to see from a customisation I'm looking to reuse?"

Some WIP suggestions might be (some have their own subsections below):
- React render components
  - Components intended for downstream customisation should expose deliberate overrides and extension points 
    - Whole-page layouts
    - Functionality blocks like a status box, or submit checklist box
  - Potentially including some way to shift layouts for full page layouts (think "blocks" from Jinja)
- Dependency management
  - Better declarations (somehow) of NPM hard dependencies, peer dependencies and potentially dev dependencies
  - I need a better understanding of how this works currently, but frontend components COULD be a new React tree for isolated dependencies or rendered inline, using the same deps. Care should be taken that things don't drift out of line.

## Shared state and module ownership

Invenio extensions may share a redux store (or zustand, or otherwise), but accessing that directly is implicitly splitting ownership across those modules.
Any changes to the shape of that data or state by the legitimate owner of the data will then lead to regressions and breakages in downstream modules using it.

For example, invenio-curations shouldn't need to know how RDN organises its deposit state. RDM could instead expose a public hook allowing for curations to access the current record without directly depending on RDM's internal choices of state management.

Hypothetically:
```jsx
// Hypothetical public RDM API
import { useDepositRecord } from "@invenio/rdm-hooks";

const record = useDepositRecord();
```

Here, the (currently non-existant) rdm-hooks owns three things:
1. How the record is stored — Redux, React context, React Query, or something else entirely.
2. How consumers access it — through useDepositRecord().
3. What the returned record looks like — its documented shape, fields and semantics.

Wherever possible, extensions, modules and customisations should consume public selectors, hooks and operations provided by whatever actually owns that state slice.

TypeScript interfaces would make these contracts easier to discover and enforce, but TypeScript itself shouldn't be a requirement for achieving this level of modularity. A documented JavaScript interface with appropriate versioning and care taken when adding, changing or removing fields can give the same public contract.

The aim is not to discourage shared state, but to make the dependencies between modules explicit and maintainable.

## API logic handling
Currently `react-invenio-forms` exposes a http client built on `axios`, which multiple other modules and extensions have made use of, making it the current de-facto http client for invenio. It includes useful defaults such as CSRF handling, credentials and content negotiation.

This is useful functionality, but it isn't specific to either React or Formik, and requiring a forms package to make API calls seems like a poor separation of concerns. In the level 2/3 world it's understandable since that dependency already exists, in the level 4 and beyond world it is necessary to move it elsewhere.

It may make sense to move this work into a dedicated package `invenio-client` which could then be consumed by `react-invenio-forms` and other Invenio extensions if they wish.

Such a package could centralise the concepts like authentication, CSRF handling and content negotiation without requiring every extension to adopt the same underlying HTTP implementation.

Importantly though, any extension hould remain free to roll their own clients, perhaps using `ky` instead of `axios`. The aim would be to provide reusable infrastructure and consistent conventions, not to restrict the entire project to a single choice.

Beyond the default client itself, I'd suggest some guidelines:
- Separate API operations from their UI components
  - Functionality for saving a draft or creating a curation request should be accessible without _needing_ to render the component that performs it.
  - This doesn't necessitate multiple NPM packages, but it may be helpful to split them into ui/logic eventually to keep concerns separated.
- Allow modules to manage their own request state
  - A central solution like Tanstack Query could be a useful option to hook into, but shouldn't be a _requirement_ for level 4.
  - Modules should be free to manage their own loading, polling and caching if they wish.
  - Modules should provide supported ways to refresh or react to changes in data without needing to know the underlying technology, cache structure or keys.
- Expose supported ways to react to operations
  - Callbacks, hooks, side effects should be provided so that if an operation succeeds, fails, succeeds with warning, whatever, the consuming code can do what they need to do without having to dig into underlying state and manage it themselves.
- Document public API contracts
  - Inputs, outputs and side effects managed by each module are treated as part of the public interface. Changes to those are breaking changes, and should be versioned as such.
  - Typescript definitions can help to make those loud and obvious, but aren't a requirement.


## Cross-module dependencies
Some extensions will directly depend on functionality provided by others. For example Curations needs to access the current deposit record from RDM (treating RDM as an extension of Invenio here, as these ideas can apply beyond InvenioRDM in theory).

These dependencies _should_ be explicit, including supported versions of packages and any providers or application state required.

The consuming application or extension should be responsible for combining behaviours and supplying any shared infrastructure. Individual extensions can bring their own providers and state structures but shouldn't replace or duplicate state owned by another module.

Where modules affect each other's data, especially in the direct dependency examples such as above, operations should be available to allow them to remain consistent without requiring the developer to understand the underlying implementation.

For example curations might do:


```jsx

import { SaveButton } from '@invenio/rdm'; // In this example we're assuming SaveButton has an onSaveSuccess callback it performs in addition to "save", and an onSaveError
import { refreshCurationsData } from './refreshCurationsData'; // Also exported publicly

export const CurationsSave = ({
  onSaveSuccess, // Allow any downstream contributors to extend this button in the same way if they wish
  onSaveError // Ditto
}) => {
  
  const handleSaveSuccess = async (savedRecord) => {
    try {
      await refreshCurationsData(savedRecord.id); // side effect behaviour could be built upon externally by copying this.
    } catch (error) {
      // Handle or report the Curations refresh failure.
      // The RDM save itself has still succeeded.
      console.error("Unable to refresh Curations data", error);
    }

    await onSaveSuccess?.(savedRecord);
  };
  
  return (
    <SaveButton
      onSaveSuccess={handleSaveSuccess}
      onSaveError={(error) => onSaveError?.(error)} // Can add in custom error handling here
    />
  )
}
```

This way a downstream customisation (or extension) could simply extend the existing Curations button:

```jsx

import { CurationsSave } from "@invenio/curations";

const CustomSave = () => {
  return (
    <CurationsSave
      onSaveSuccess={(savedRecord) => {
        console.log("Deposit saved:", savedRecord);
      }}
    />
  );
};
```
or it could build its own component using the publicly exposed functionality from RDM and Curations:

```jsx
import { SaveButton } from "@invenio/rdm";
import { refreshCurationsData } from "@invenio/curations";

const CustomSave = () => {
  const handleSaveSuccess = async (savedRecord) => {
    await refreshCurationsData(savedRecord.id);

    // Custom behaviour specific to this implementation
    console.log("Deposit saved:", savedRecord);
  };

  return <SaveButton onSaveSuccess={handleSaveSuccess} />;
};
```

In this example, Curations extends RDM's public `SaveButton` behaviour, while still exposing its own component for further customisation.

A downstream extension could use `CurationsSave` directly and attach its own callbacks, or compose RDM's `SaveButton` with Curations' publicly exported API functionality to create something different.

The important distinction is that neither approach requires access to internal component methods or state. Some orchestration logic may be repeated, but the underlying behaviour remains owned by the appropriate module and available through its public API.

Ideally, `SaveButton` itself would also use publicly exposed hooks or operations to perform its work. This would allow a downstream customisation to reuse the same save behaviour without having to render the button, or to combine it with other operations in a different order.

For example, a customisation might need to perform additional work before saving, save the record, and then create a curation request. Those operations should be independently accessible rather than requiring developers to work around the lifecycle of an existing component.