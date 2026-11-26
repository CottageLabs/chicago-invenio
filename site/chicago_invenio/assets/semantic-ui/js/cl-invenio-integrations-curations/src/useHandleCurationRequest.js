import {
  useLatestCurationRequest,
  useCreateCurationRequest,
  useResubmitCurationRequest
} from "./api";

// All in one hook to provide all of the API hooks in a single place for ease of use
export const useHandleCurationRequest = (
  recordId,
  options = {}
) => {
  const latest = useLatestCurationRequest(
    recordId,
    options
  );

  const create = useCreateCurationRequest();
  const resubmit = useResubmitCurationRequest();

  return {
    latestRequest: latest.latestRequest,
    requestId: latest.requestId,

    isSuccess: latest.isSuccess,

    isLoading:
      latest.isLoading ||
      create.isLoading ||
      resubmit.isLoading,

    isRefreshing: latest.isRefreshing,

    error:
      latest.error ||
      create.error ||
      resubmit.error,

    refresh: latest.refresh,

    createRequest: () =>
      create.createRequest(recordId),

    // By default assume we're resubmitting the last thing we fetched
    resubmitRequest: (
      request = latest.latestRequest
    ) => resubmit.resubmitRequest(request),
  };
};