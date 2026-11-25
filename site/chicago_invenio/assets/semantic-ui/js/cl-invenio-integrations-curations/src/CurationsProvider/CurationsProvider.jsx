import {
  createIntegrationQueryProvider,
} from "@cottagelabs/invenio-integrations-core/query";

// centralised this logic so every integration can choose
// to get the SAME behaviour and extensibility if they wish
export const {
  Provider: CurationsProvider,
  QueryContext: CurationsQueryContext,
  defaultQueryClient,
} = createIntegrationQueryProvider();