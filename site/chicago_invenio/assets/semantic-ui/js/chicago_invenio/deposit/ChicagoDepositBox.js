import React from "react";
import { Card, Form, Grid, Message } from "semantic-ui-react";
import { PreviewButton, SaveButton } from "@js/invenio_rdm_records";
import { DepositBoxComponent } from "@js/invenio_curations/deposit/DepositBox";
import { CustomDepositStatusBox } from "@js/invenio_curations/deposit/CustomDepositStatusBox";
import { RequestOrPublishButton } from "@js/invenio_curations/deposit/RequestOrPublishButton";
import { ShareDraftButton } from "@js/invenio_app_rdm/deposit/ShareDraftButton";
import { connect } from "react-redux";
import { connect as connectFormik } from "formik";

class ChicagoDepositBoxComponent extends DepositBoxComponent {
  constructor(props) {
    super(props);
    this.state = { ...this.state, communityError: false };
  }

  componentDidUpdate() {
    if (this.state.communityError && this.hasCommunitySelected()) {
      this.setState({ communityError: false });
    }
  }

  hasCommunitySelected() {
    const { selectedCommunity } = this.props;
    return !!selectedCommunity;
  }

  render() {
    const { latestRequest, curationsData, communityError } = this.state;
    const { record, permissions, groupsEnabled } = this.props;
    

    this.checkShouldFetchCurationRequest();

    return (
      <Card className="access-right">
        <Form.Field required>
          <Card.Content>
            <CustomDepositStatusBox
              record={this.record}
              request={latestRequest}
              key={`status-${this.record?.id}-${latestRequest?.id}`}
            />
          </Card.Content>

          <Card.Content>
            <Grid relaxed>
              <Grid.Column computer={8} mobile={16} className="pb-0 left-btn-col">
                <SaveButton fluid />
              </Grid.Column>

              <Grid.Column computer={8} mobile={16} className="pb-0 right-btn-col">
                <PreviewButton fluid />
              </Grid.Column>

              <Grid.Column width={16} className="pt-10 pb-10">
                {communityError && (
                  <Message negative size="small">
                    Please select a community before submitting for curation review.
                  </Message>
                )}
                <RequestOrPublishButton
                  request={latestRequest}
                  record={this.record}
                  curationsData={curationsData}
                  loading={this.loading}
                  handleCreateRequest={async (event) => {
                    if (!this.hasCommunitySelected()) {
                      this.setState({ communityError: true });
                      return;
                    }
                    this.setState({ communityError: false });
                    this.handleSave(event);
                    await this.fetchCurationRequest();
                    await this.createCurationRequest();
                  }}
                  handleResubmitRequest={async (event) => {
                    this.handleSave(event);
                    await this.resubmitCurationRequest();
                  }}
                />
              </Grid.Column>

              <Grid.Column width={16} className="pt-0">
                {(record.is_draft === null || permissions.can_manage) && (
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
  }
}

const mapStateToProps = (state) => ({
  stateRecordId: state.deposit?.record?.id,
  selectedCommunity: state.deposit?.editorState?.selectedCommunity,
});

export const ChicagoDepositBox = connect(
  mapStateToProps,
  null
)(connectFormik(ChicagoDepositBoxComponent));
