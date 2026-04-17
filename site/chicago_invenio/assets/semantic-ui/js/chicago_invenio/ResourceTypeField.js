// ResourceTypeField.js
import React, { useMemo, useCallback } from "react";
import PropTypes from "prop-types";
import { FieldLabel, SelectField } from "react-invenio-forms";
import { i18next } from "@translations/invenio_rdm_records/i18next";

const formatLabel = (option) =>
  option.type_name + (option.subtype_name ? " / " + option.subtype_name : "");

export const ResourceTypeField = ({
  fieldPath,
  label,
  labelIcon,
  options,
  ...restProps
}) => {
  const frontEndOptions = useMemo(
    () =>
      options
        .map((o) => ({ ...o, label: formatLabel(o) }))
        .sort((o1, o2) => o1.label.localeCompare(o2.label))
        .map((o) => ({
          value: o.id,
          icon: o.icon,
          text: o.label,
        })),
    [options]
  );

  const handleChange = useCallback(
    ({ data, formikProps }) => {
      const value = data?.value;
      const selectedOption = options?.find((o) => o.id === value) || null;

      if (formikProps?.form) {
        const { setFieldValue } = formikProps.form;
        setFieldValue(fieldPath, value);
        setFieldValue("_selectedResourceType", selectedOption);
      }
    },
    [fieldPath, options]
  );

  return (
    <SelectField
      fieldPath={fieldPath}
      label={<FieldLabel htmlFor={fieldPath} icon={labelIcon} label={label} />}
      optimized
      aria-label={label}
      options={frontEndOptions}
      selectOnBlur={false}
      onChange={handleChange}
      {...restProps}
    />
  );
};

ResourceTypeField.propTypes = {
  fieldPath: PropTypes.string.isRequired,
  label: PropTypes.string,
  labelIcon: PropTypes.string,
  options: PropTypes.arrayOf(
    PropTypes.shape({
      icon: PropTypes.string,
      type_name: PropTypes.string,
      subtype_name: PropTypes.string,
      id: PropTypes.string,
    })
  ).isRequired,
};

ResourceTypeField.defaultProps = {
  label: i18next.t("Resource type"),
  labelIcon: "tag",
};

export default ResourceTypeField;
