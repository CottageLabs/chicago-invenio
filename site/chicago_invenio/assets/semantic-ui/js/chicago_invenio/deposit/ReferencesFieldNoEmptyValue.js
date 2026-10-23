import React from "react";
import { ReferencesField } from "@js/invenio_rdm_records";
import { i18next } from "@translations/invenio_rdm_records/i18next";

// Renders ReferencesField without a pre-populated empty row, so only the
// "Add reference" button shows until the user chooses to add one, and adds
// a helpText description, matching the style of the description already
// shown under Related works.
export const ReferencesFieldNoEmptyValue = (props) => (
  <ReferencesField
    {...props}
    showEmptyValue={false}
    helpText={i18next.t(
      "Add a full citation for each work referenced by this record, e.g. in APA or Chicago style."
    )}
  />
);
