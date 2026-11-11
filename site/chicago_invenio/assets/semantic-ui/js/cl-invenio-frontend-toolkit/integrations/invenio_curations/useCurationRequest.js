// integrations/invenio_curations/useCurationRequest.js

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { curationClient } from "./curationClient";

export const useCurationRequest = (recordId) => {
  const queryClient = useQueryClient();

  const queryKey = ["curations", "latest-request", recordId];

  console.log("RecordId: %o", recordId)

  const requestQuery = useQuery({
    queryKey,
    queryFn: async () => await curationClient.getLatestRequest(recordId),
    enabled: Boolean(recordId),
    refetchInterval: 10_000,
  });

  const createMutation = useMutation({
    mutationFn: () => curationClient.createRequest(recordId),
    onSuccess: (request) => {
      queryClient.setQueryData(queryKey, request);
    },
  });

  const resubmitMutation = useMutation({
    mutationFn: (request) =>
      curationClient.resubmitRequest(request),
    onSuccess: (request) => {
      queryClient.setQueryData(queryKey, request);
    },
  });

  return {
    latestRequest: requestQuery.data ?? null,

    isLoading:
      requestQuery.isFetching ||
      createMutation.isLoading ||
      resubmitMutation.isLoading,

    error:
      requestQuery.error ||
      createMutation.error ||
      resubmitMutation.error,

    refresh: requestQuery.refetch,

    createRequest: createMutation.mutateAsync,
    resubmitRequest: resubmitMutation.mutateAsync,
  };
};