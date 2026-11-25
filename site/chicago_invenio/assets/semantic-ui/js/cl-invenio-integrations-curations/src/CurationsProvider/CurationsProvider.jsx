import React, { createContext, useState } from "react";
import {
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";

export const CurationsQueryContext = createContext(undefined);

export const CurationsProvider = ({
  children,
  queryClient,
}) => {
  const [defaultClient] = useState(() => new QueryClient());

  return (
    <QueryClientProvider
      client={queryClient ?? defaultClient}
      context={CurationsQueryContext}
    >
      {children}
    </QueryClientProvider>
  );
};