// This file is part of Invenio-RDM-Records
// Copyright (C) 2020-2023 CERN.
// Copyright (C) 2020-2022 Northwestern University.
// Copyright (C) 2021 Graz University of Technology.
//
// Invenio-RDM-Records is free software; you can redistribute it and/or modify it
// under the terms of the MIT License; see LICENSE file for more details.

import React from "react";
import PropTypes from "prop-types";
import { useFormikContext } from "formik";

import { FieldLabel, TextField } from "react-invenio-forms";
import { i18next } from "@translations/invenio_rdm_records/i18next";

export function VersionField({ fieldPath, label, labelIcon, placeholder, showWhenResourceTypes = [] }) {
  const { values } = useFormikContext();
  
  // Debug logging
  console.log('VersionField render - values:', values);
  console.log('VersionField render - _selectedResourceType:', values?._selectedResourceType);
  console.log('VersionField render - showWhenResourceTypes:', showWhenResourceTypes);
  
  const shouldRender = () => {
    if (showWhenResourceTypes.length === 0) {
      return true; // Show by default if no conditions specified
    }
    
    const selectedResourceType = values?._selectedResourceType;
    
    if (!selectedResourceType) {
      console.log('VersionField: No selected resource type, hiding');
      return false;
    }
    
    const shouldShow = showWhenResourceTypes.includes(selectedResourceType.id);
    console.log('VersionField: Should show?', shouldShow, 'for type:', selectedResourceType.id);
    return shouldShow;
  };

  const renderDecision = shouldRender();
  console.log('VersionField: Final render decision:', renderDecision);
  
  if (!renderDecision) {
    return null;
  }

  const helpText = (
    <span>
      {i18next.t(
        "Mostly relevant for software and dataset uploads. A semantic version string is preferred see"
      )}
      <a href="https://semver.org/" target="_blank" rel="noopener noreferrer">
        {" "}
        semver.org
      </a>
      {i18next.t(", but any version string is accepted.")}
    </span>
  );

  return (
    <TextField
      fieldPath={fieldPath}
      helpText={helpText}
      label={<FieldLabel htmlFor={fieldPath} icon={labelIcon} label={label} />}
      placeholder={placeholder}
    />
  );
}

VersionField.propTypes = {
  fieldPath: PropTypes.string.isRequired,
  label: PropTypes.string,
  labelIcon: PropTypes.string,
  placeholder: PropTypes.string,
  showWhenResourceTypes: PropTypes.arrayOf(PropTypes.string),
};

VersionField.defaultProps = {
  label: i18next.t("Version"),
  labelIcon: "code branch",
  placeholder: "",
};

export default VersionField;