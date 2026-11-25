import React, { createContext } from "react";
import {
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";

export const CurationsQueryContext = createContext(undefined);
export const defaultQueryClient = new QueryClient();

export const CurationsProvider = ({
  children,
  queryClient = defaultQueryClient,
}) => {

  return (
    <QueryClientProvider
      client={queryClient}
      context={CurationsQueryContext}
    >
      {children}
    </QueryClientProvider>
  );
};