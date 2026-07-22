import React from "react";
import { RelatedWorksField } from "@js/invenio_rdm_records";

// Renders RelatedWorksField without a pre-populated empty row, so only the
// "Add related work" button shows until the user chooses to add one.
export const RelatedWorksFieldNoEmptyValue = (props) => (
  <RelatedWorksField {...props} showEmptyValue={false} />
);
