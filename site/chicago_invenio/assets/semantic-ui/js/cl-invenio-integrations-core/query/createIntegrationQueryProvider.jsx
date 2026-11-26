import React, { createContext } from "react";

import * as TanStackQuery from "@tanstack/react-query";


// Set up the integration query providers.
// It is important that each provider is by default context
// bound and that the hooks automatically bind to that context.
export const createIntegrationQueryProvider = () => {
  const QueryContext = createContext(undefined);
  const defaultQueryClient = new TanStackQuery.QueryClient();

  const Provider = ({
    children,
    queryClient = defaultQueryClient,
  }) => (
    <TanStackQuery.QueryClientProvider
      client={queryClient}
      context={QueryContext}
    >
      {children}
    </TanStackQuery.QueryClientProvider>
  );

  const useQuery = (options) =>
    TanStackQuery.useQuery({
      ...options,
      context: QueryContext, // Context is ALWAYS bound and not overrideable.
    });

  const useMutation = (options) =>
    TanStackQuery.useMutation({
      ...options,
      context: QueryContext, // Context is ALWAYS bound and not overrideable.
    });

  const useQueryClient = () =>
    TanStackQuery.useQueryClient({
      context: QueryContext, // Context is ALWAYS bound and not overrideable.
    });


  return {
    Provider,
    QueryContext,
    defaultQueryClient,
    Query: {
      useQuery,
      useMutation,
      useQueryClient,
    },
  };
};