import { http } from "react-invenio-forms";

export const curationClient = {
  async getLatestRequest(recordId) {
    console.log(`curationClient::getLatestRequest(${recordId})`)
    const response = await http.get("/api/curations/", {
      params: {
        expand: 1,
        topic: `record:${recordId}`,
      },
    });

    console.log("Resp: %o", response)

    const hits = response.data.hits;

    return hits.total > 0 ? hits.hits[0] : null;
  },

  async getCurationsData() {
    const response = await http.get("/api/curations/data");
    return response.data;
  },

  async createRequest(recordId) {
    const response = await http.post(
      "/api/curations/",
      { topic: { record: recordId } },
      { params: { expand: 1 } }
    );

    return response.data;
  },

  async resubmitRequest(request) {
    const resubmitUrl = new URL(
      request.links.actions.resubmit,
      window.location.origin
    );

    const response = await http.post(
      `${resubmitUrl.pathname}${resubmitUrl.search}`
    );

    return response.data;
  },
};