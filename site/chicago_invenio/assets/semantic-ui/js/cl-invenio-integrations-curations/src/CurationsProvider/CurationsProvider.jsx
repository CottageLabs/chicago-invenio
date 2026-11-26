import {
  createIntegrationQueryProvider,
} from "@cottagelabs/invenio-integrations-core/query";

// centralised this logic so every integration can choose
// to get the SAME behaviour and extensibility if they wish
export const {
  Provider: CurationsProvider,
  QueryContext: CurationsQueryContext,
  defaultQueryClient,
  Query: CurationsQuery,
} = createIntegrationQueryProvider();

// Within Curations it's easier to use the direct API,
// but in implementations using multiple integrations,
// it's better to be able to tell which Query you're
// using at a glance, ie CurationsQuery.useQuery
export const {
  useQueryClient,
  useQuery,
  useMutation
} = CurationsQuery;
