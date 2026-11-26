// integrations/invenio_curations/src/api/useResubmitCurationRequest.js

import {
  useMutation,
  useQueryClient,
} from "../CurationsProvider";

import { curationClient } from "./curationClient";
import { getRequestQueryKey } from "./queryKeys";

export const useResubmitCurationRequest = () => {
  const queryClient = useQueryClient();

  const resubmitMutation = useMutation({
    mutationFn: (request) =>
      curationClient.resubmitRequest(request),

    onSuccess: (request) => {
      queryClient.setQueryData(
        getRequestQueryKey(request.id),
        request
      );
    },
  });

  return {
    isLoading: resubmitMutation.isLoading,
    error: resubmitMutation.error,
    resubmitRequest: resubmitMutation.mutateAsync,
  };
};