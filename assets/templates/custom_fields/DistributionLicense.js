import React, { useState, useEffect } from "react";
import { useFormikContext, getIn } from "formik";
import { FieldLabel } from "react-invenio-forms";
import { Checkbox, Form } from "semantic-ui-react";
import PropTypes from "prop-types";

export const DistributionLicense = ({ fieldPath, label, description, icon }) => {
  const { values, setFieldValue, setFieldTouched, touched, submitCount } = useFormikContext();
  const [wasAttempted, setWasAttempted] = useState(false);

  const value = getIn(values, fieldPath);
  const isChecked = value === "I agree";

  useEffect(() => {
    if (submitCount > 0) setWasAttempted(true);
  }, [submitCount]);

  const isTouched = getIn(touched, fieldPath) || wasAttempted;
  const hasError = isTouched && !isChecked;

  return (
    <Form.Field required error={hasError}>
      {label && <FieldLabel htmlFor={fieldPath} icon={icon} label={label} />}
      <Checkbox
        id={fieldPath}
        name={fieldPath}
        label={description}
        checked={isChecked}
        onChange={(_, { checked }) => {
          setFieldValue(fieldPath, checked ? "I agree" : "");
          setFieldTouched(fieldPath, true);
        }}
      />
      {hasError && (
        <div className="ui pointing above prompt label">
          You must agree to the distribution license before submitting.
        </div>
      )}
    </Form.Field>
  );
};

DistributionLicense.propTypes = {
  fieldPath: PropTypes.string.isRequired,
  label: PropTypes.string,
  description: PropTypes.string,
  icon: PropTypes.string,
};

DistributionLicense.defaultProps = {
  label: undefined,
  description: undefined,
  icon: "legal",
};
