// integrations/invenio_curations/src/api/useCreateCurationRequest.js

import {
  useMutation,
  useQueryClient,
} from "../CurationsProvider";
import { curationClient } from "./curationClient";
import { getLatestRequestQueryKey, getRequestQueryKey } from "./queryKeys";

export const useCreateCurationRequest = (
  recordId
) => {
  const queryClient = useQueryClient();

  const latestRequestQueryKey = getLatestRequestQueryKey(recordId);

  const createMutation = useMutation({
    mutationFn: () => curationClient.createRequest(recordId),
    onSuccess: (request) => {
      queryClient.setQueryData(latestRequestQueryKey, request);
      // We have request id so we can also reset the query cache for direct request query
      queryClient.setQueryData(getRequestQueryKey(request.id), request);
    },
  });

  return {

    isLoading: createMutation.isLoading,
    error: createMutation.error,
    createRequest: createMutation.mutateAsync,
  };
};