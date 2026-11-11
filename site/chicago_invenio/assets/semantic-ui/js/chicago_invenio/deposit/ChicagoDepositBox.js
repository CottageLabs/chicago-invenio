import React, { useEffect, useMemo, useState } from "react";
import { useSelector } from "react-redux";
import { Card, Form, Grid, Message } from "semantic-ui-react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { PreviewButton, SaveButton } from "@js/invenio_rdm_records";
import { CustomDepositStatusBox } from
  "@js/invenio_curations/deposit/CustomDepositStatusBox";
import { RequestOrPublishButton } from
  "@js/invenio_curations/deposit/RequestOrPublishButton";
import { ShareDraftButton } from
  "@js/invenio_app_rdm/deposit/ShareDraftButton";

import {
  useDepositSubmit,
  useDepositStateChange,
  useCurationRequest,
  useCurationsData,
  DRAFT_SAVE_SUCCEEDED,
  DRAFT_SAVE_STARTED,
  DRAFT_SAVE_FAILED
} from "@cl-toolkit";

const ChicagoDepositBoxContent = ({
  record,
  permissions,
  groupsEnabled,
}) => {
  const recordId = useSelector(
    (state) => state.deposit?.record?.id
  ) || record.id;

  console.log("RECORDID: %o", recordId)

  const hasCommunitySelected = useSelector(
    (state) => Boolean(
      state.deposit?.editorState?.selectedCommunity
    )
  );

  const [communityError, setCommunityError] = useState(false);
  const [submissionError, setSubmissionError] = useState(null);

  const { saveDraft } = useDepositSubmit();

  const {
    latestRequest,
    isLoading,
    error: curationError,
    createRequest,
    resubmitRequest,
    refresh,
  } = useCurationRequest(recordId);

  console.log("Latest Request: %o", latestRequest)
  console.log("Record: %o", record)
  console.log("RecordID: %o", recordId)

  const { curationsData } = useCurationsData();
  const [savedSuccessfully, setSavedSuccessfully] = useState(false);

  useDepositStateChange({
    [DRAFT_SAVE_STARTED]: () => {
      setSavedSuccessfully(false);
    },
    [DRAFT_SAVE_SUCCEEDED]: () => {
      setSavedSuccessfully(true);
      refresh();
    },
    [DRAFT_SAVE_FAILED]: () => {
      setSavedSuccessfully(false);
      refresh();
    },
  });

  const currentRecord = useMemo(() => ({
    ...record,
    id: recordId,
    savedSuccessfully,
  }), [record, recordId, savedSuccessfully]);

  // Clear the community error when a community is selected.
  useEffect(() => {
    if (hasCommunitySelected) {
      setCommunityError(false);
    }
  }, [hasCommunitySelected]);

  const handleCreateRequest = async () => {
    if (!hasCommunitySelected) {
      setCommunityError(true);
      return;
    }

    setCommunityError(false);
    setSubmissionError(null);

    return saveDraft()
      .then(() => refresh())
      .then(() => createRequest())
      .then(() => {
        console.log("Curation request created");
      })
      .catch((error) => {
        console.error("Failed to create curation request:", error);
        setSubmissionError("Unable to create the curation request.");
      });
  };

  const handleResubmitRequest = async () => {
    setSubmissionError(null);

    return saveDraft()
      .then(() => resubmitRequest(latestRequest))
      .then(() => {
        console.log("Curation request resubmitted");
      })
      .catch((error) => {
        console.error("Failed to resubmit curation request:", error);
        setSubmissionError("Unable to resubmit the curation request.");
      });
  };

  return (
    <Card className="access-right">
      <Form.Field required>
        <Card.Content>
          <CustomDepositStatusBox
            record={currentRecord}
            request={latestRequest}
            key={`status-${recordId}-${latestRequest?.id}`}
          />
        </Card.Content>

        <Card.Content>
          <Grid relaxed>
            <Grid.Column
              computer={8}
              mobile={16}
              className="pb-0 left-btn-col"
            >
              <SaveButton fluid />
            </Grid.Column>

            <Grid.Column
              computer={8}
              mobile={16}
              className="pb-0 right-btn-col"
            >
              <PreviewButton fluid />
            </Grid.Column>

            <Grid.Column
              width={16}
              className="pt-10 pb-10"
            >
              {communityError && (
                <Message negative size="small">
                  Please select a community before submitting
                  for curation review.
                </Message>
              )}

              {submissionError && (
                <Message negative size="small">
                  {submissionError}
                </Message>
              )}

              {curationError && (
                <Message negative size="small">
                  Unable to load curation information.
                </Message>
              )}

              <RequestOrPublishButton
                request={latestRequest}
                record={currentRecord}
                curationsData={curationsData}
                loading={isLoading}
                handleCreateRequest={handleCreateRequest}
                handleResubmitRequest={handleResubmitRequest}
              />
            </Grid.Column>

            <Grid.Column width={16} className="pt-0">
              {(record.is_draft === null ||
                permissions?.can_manage) && (
                <ShareDraftButton
                  record={record}
                  permissions={permissions}
                  groupsEnabled={groupsEnabled}
                />
              )}
            </Grid.Column>
          </Grid>
        </Card.Content>
      </Form.Field>
    </Card>
  );
};

const queryClient = new QueryClient();

export const ChicagoDepositBox = (props) => (
  <QueryClientProvider client={queryClient}>
    <ChicagoDepositBoxContent {...props} />
  </QueryClientProvider>
);
