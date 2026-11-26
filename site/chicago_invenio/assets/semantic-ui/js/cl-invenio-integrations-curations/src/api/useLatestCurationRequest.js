// integrations/invenio_curations/src/api/useLatestCurationRequest.js

import {
  useQuery,
  useQueryClient,
} from "../CurationsProvider";

import { curationClient } from "./curationClient";
import { useCurationRequest } from "./useCurationRequest";

import {
  getLatestRequestQueryKey,
  getRequestQueryKey,
} from "./queryKeys";

// Handles polling latest curation request until it finds one, then
export const useLatestCurationRequest = (
  recordId,
  {
    pollInterval = 10_000,
  } = {}
) => {
  const queryClient = useQueryClient();


  // This query returns the request ID alone
  const discoveryQuery = useQuery({
    queryKey: getLatestRequestQueryKey(recordId),

    queryFn: async () => {
      const request =
        await curationClient.getLatestRequest(recordId);

      if (request) {
        // Seed the request cache if it isn't already populated.
        queryClient.setQueryData(
          getRequestQueryKey(request.id),
          (previous) => previous ?? request
        );
      }

      return request?.id ?? null;
    },

    enabled: Boolean(recordId),

    // Poll discovery until we know the request ID.
    refetchInterval: (requestId) =>
      requestId ? false : pollInterval,
  });

  const requestId = discoveryQuery.data;

  const {
    request,
    isSuccess,
    isLoading,
    isRefreshing,
    error,
  } = useCurationRequest(requestId, {
    pollInterval,
  });

  const refresh = async () => {
    if (!recordId) {
      return undefined;
    }

    // Explicit refreshes rediscover the association.
    const result = await discoveryQuery.refetch({
      throwOnError: true,
    });

    if (result.data === null) {
      return null;
    }

    return queryClient.fetchQuery({
      queryKey: getRequestQueryKey(result.data),
      queryFn: () =>
        curationClient.getRequest(result.data),
    });
  };

  return {
    requestId,

    latestRequest:
      requestId === null ? null : request,

    isSuccess:
      discoveryQuery.isSuccess &&
      (requestId === null || isSuccess),

    isLoading:
      discoveryQuery.isInitialLoading ||
      isLoading,

    isRefreshing:
      discoveryQuery.isRefetching ||
      isRefreshing,

    error: discoveryQuery.error || error,

    refresh,
  };
};