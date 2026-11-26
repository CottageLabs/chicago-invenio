// integrations/invenio_curations/src/api/useCurationRequest.js

import {
  useQuery,
} from "../CurationsProvider";
import { curationClient } from "./curationClient";
import { getRequestQueryKey } from "./queryKeys";

export const useCurationRequest = (
  requestId,
  {
    pollInterval = false, // Don't poll by default
  } = {}
) => {
  const queryKey = getRequestQueryKey(requestId);

  console.log("RequestId: %o", requestId)

  const requestQuery = useQuery({
    queryKey,
    queryFn: async () => await curationClient.getRequest(requestId),
    enabled: Boolean(requestId),
    refetchInterval: pollInterval
  });

  return {
    request: requestQuery.data,
    isSuccess: requestQuery.isSuccess,
    isLoading: requestQuery.isInitialLoading,
    isRefreshing: requestQuery.isRefetching,
    error: requestQuery.error,
    refresh: requestQuery.refetch,
  };
};