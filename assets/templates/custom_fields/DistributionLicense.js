import React, { useState, useEffect } from "react";
import { useFormikContext, getIn } from "formik";
import { FieldLabel } from "react-invenio-forms";
import { Checkbox, Form } from "semantic-ui-react";
import PropTypes from "prop-types";

const RIGHTS_FIELD = "metadata.rights";

export const DistributionLicense = ({ fieldPath, label, description, icon, license }) => {
  const { values, setFieldValue, setFieldTouched, touched, submitCount } = useFormikContext();
  const [wasAttempted, setWasAttempted] = useState(false);

  const value = getIn(values, fieldPath);
  const isChecked = value === "I agree";

  useEffect(() => {
    if (submitCount > 0) setWasAttempted(true);
  }, [submitCount]);

  // Sync checkbox from rights field: if the license is removed from rights, uncheck the box
  useEffect(() => {
    const rights = getIn(values, RIGHTS_FIELD) || [];
    const licensePresent = rights.some((r) => r.id === license.id);
    if (isChecked && !licensePresent) {
      setFieldValue(fieldPath, "");
    }
  }, [getIn(values, RIGHTS_FIELD)]);

  const isTouched = getIn(touched, fieldPath) || wasAttempted;
  const hasError = isTouched && !isChecked;

  const handleChange = (_, { checked }) => {
    setFieldValue(fieldPath, checked ? "I agree" : "");
    setFieldTouched(fieldPath, true);

    // Sync the license into/out of metadata.rights
    const rights = getIn(values, RIGHTS_FIELD) || [];
    if (checked) {
      const alreadyPresent = rights.some((r) => r.id === license.id);
      if (!alreadyPresent) {
        setFieldValue(RIGHTS_FIELD, [...rights, license]);
      }
    } else {
      setFieldValue(RIGHTS_FIELD, rights.filter((r) => r.id !== license.id));
    }
  };

  return (
    <Form.Field required error={hasError}>
      {label && <FieldLabel htmlFor={fieldPath} icon={icon} label={label} />}
      <Checkbox
        id={fieldPath}
        name={fieldPath}
        label={description}
        checked={isChecked}
        onChange={handleChange}
      />
      {hasError && (
        <div className="ui pointing above prompt label">
          You must agree to the distribution license before submitting.
        </div>
      )}
      <div style={{ paddingTop: "0.9rem" }}>
        Further information: <a href="/distribution-license">UChicago Knowledge Deposit Agreement</a>
      </div>
    </Form.Field>
  );
};

DistributionLicense.propTypes = {
  fieldPath: PropTypes.string.isRequired,
  label: PropTypes.string,
  description: PropTypes.string,
  icon: PropTypes.string,
  license: PropTypes.shape({
    id: PropTypes.string.isRequired,
    title: PropTypes.string,
    description: PropTypes.string,
    link: PropTypes.string,
  }),
};

DistributionLicense.defaultProps = {
  label: undefined,
  description: undefined,
  icon: "legal",
  license: {
    title: "Distribution license",
    description: "University of Chicago standard distribution license.",
    link: "https://knowledge.uchicago.edu/pages/?page=Distribution+License&ln=en",
  },
};