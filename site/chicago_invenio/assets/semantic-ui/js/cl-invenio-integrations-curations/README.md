# CottageLabs Invenio Integrations | Curations

This is the Curations flavour CottageLabs integration library.

## CurationsProvider
The Curations integration makes use of TanStackQuery to manage query caching and other goodies. In order to best provide the context for this, it has CurationsQueryContext and CurationsProvider. This allows a component to immideately get up and running using the provided hooks:

```jsx
import {
  CurationsProvider,
  useCurationRequest
} from "@cottagelabs/invenio-integrations-curations";

const MyComponentCmp = () => {
  const { refresh } = useCurationRequest();
  return (
    <button onClick={() => refresh()}>Refresh</button>
  );
};

export const MyComponent = () => (
  <CurationsProvider>
    <MyComponentCmp/>
  </CurationsProvider>
);
```
This allows a component to get off the ground instantly, and by default all components using the provider will share the same QueryClient. However, in the event that other React contexts are provided directly, siblings rendered in parallel CurationsProviders may not be able to share data, so the Provider should be placed as high in the tree as possible.

The pattern implemented for the CurationsProvider also allows two instances to explicitly share a queryClient, or to have deliberately isolated queryClients, by passing in queryClient as a prop. This could ALSO be used in tandem with some other integration model set up in the same way to allow two integrations to share a queryClient at the implementation level.