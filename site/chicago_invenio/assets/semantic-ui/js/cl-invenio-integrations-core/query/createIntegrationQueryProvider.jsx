import React, { createContext } from "react";
import {
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";

export const createIntegrationQueryProvider = () => {
  const QueryContext = createContext(undefined);
  const defaultQueryClient = new QueryClient();

  const Provider = ({
    children,
    queryClient = defaultQueryClient,
  }) => (
    <QueryClientProvider
      client={queryClient}
      context={QueryContext}
    >
      {children}
    </QueryClientProvider>
  );

  return {
    Provider,
    QueryContext,
    defaultQueryClient,
  };
};