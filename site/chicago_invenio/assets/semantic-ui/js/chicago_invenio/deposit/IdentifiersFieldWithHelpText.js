import React from "react";
import { IdentifiersField } from "@js/invenio_rdm_records";
import { i18next } from "@translations/invenio_rdm_records/i18next";

// Adds a helpText description to IdentifiersField, matching the style of
// the description already shown under Related works, and renders it without
// a pre-populated empty row, so only the "Add identifier" button shows until
// the user chooses to add one.
export const IdentifiersFieldWithHelpText = (props) => (
  <IdentifiersField
    {...props}
    showEmptyValue={false}
    helpText={i18next.t(
      "Specify alternate identifiers for this work. Supported identifiers include DOI, Handle, ARK, PURL, ISSN, ISBN, PubMed ID, PubMed Central ID, ADS Bibliographic Code, arXiv, Life Science Identifiers (LSID), EAN-13, ISTC, URNs, and URLs."
    )}
  />
);
