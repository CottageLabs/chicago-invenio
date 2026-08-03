import React from "react";
import { DatesField } from "@js/invenio_rdm_records";

// Renders DatesField without a pre-populated empty row, so only the
// "Add date" button shows until the user chooses to add one.
export const DatesFieldNoEmptyValue = (props) => (
  <DatesField {...props} showEmptyValue={false} />
);
