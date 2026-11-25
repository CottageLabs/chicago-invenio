// integrations/invenio_curations/useCurationsData.js

import { useQuery } from "@tanstack/react-query";
import { CurationsQueryContext } from "./CurationsProvider";
import { curationClient } from "./curationClient";

export const useCurationsData = () => {
  const query = useQuery({
    queryKey: ["curations", "configuration"],
    context: CurationsQueryContext,
    queryFn: curationClient.getCurationsData,
    staleTime: 60_000,
  });

  return {
    curationsData: query.data ?? null,
    context: CurationsQueryContext,
    isLoading: query.isLoading,
    error: query.error,
  };
};