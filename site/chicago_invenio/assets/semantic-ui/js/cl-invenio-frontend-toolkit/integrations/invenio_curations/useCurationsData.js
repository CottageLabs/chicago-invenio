// integrations/invenio_curations/useCurationsData.js

import { useQuery } from "@tanstack/react-query";
import { curationClient } from "./curationClient";

export const useCurationsData = () => {
  const query = useQuery({
    queryKey: ["curations", "configuration"],
    queryFn: curationClient.getCurationsData,
    staleTime: 60_000,
  });

  return {
    curationsData: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error,
  };
};