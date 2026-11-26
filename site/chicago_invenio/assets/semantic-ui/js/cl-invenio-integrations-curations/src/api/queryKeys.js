// integrations/invenio_curations/src/api/queryKeys.js

export const baseQueryKey = ["curations"];
export const baseLatestRequestQueryKey = [...baseQueryKey, "latest-request"];
export const getLatestRequestQueryKey = (recordId) => [...baseLatestRequestQueryKey, recordId];

export const baseRequestQueryKey = [...baseQueryKey, 'request'];
export const getRequestQueryKey = (requestId) => [...baseRequestQueryKey, requestId];
