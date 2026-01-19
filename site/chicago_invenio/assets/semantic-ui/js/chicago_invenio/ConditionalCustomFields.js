import React, { useMemo } from "react";
import PropTypes from "prop-types";
import { useFormikContext } from "formik";
import { CustomFields } from "react-invenio-forms";

const shouldShowByRule = (rule, resourceTypeId) => {
  if (rule.showFor?.length) {
    return rule.showFor.includes(resourceTypeId);
  }
  if (rule.hideFor?.length) {
    return !rule.hideFor.includes(resourceTypeId);
  }
  return true;
};

export function ConditionalCustomFields({
  config,
  record,
  templateLoaders,
  fieldPathPrefix,
  severityChecks,
  sectionRules = {},
}) {
  const { values } = useFormikContext();
  const resourceTypeId = values?._selectedResourceType?.id ?? null;

  const filteredConfig = useMemo(() => {
    if (Object.keys(sectionRules).length === 0) {
      return config;
    }

    return config
      .map((section) => {
        const rule = sectionRules[section.section];
        if (!rule) return section;

        // Field-level filtering
        if (rule.fieldRules) {
          const filteredFields = section.fields.filter((field) => {
            const fieldRule = rule.fieldRules[field.field];
            return fieldRule ? shouldShowByRule(fieldRule, resourceTypeId) : true;
          });

          return filteredFields.length > 0
            ? { ...section, fields: filteredFields }
            : null;
        }

        // Section-level filtering
        return shouldShowByRule(rule, resourceTypeId) ? section : null;
      })
      .filter(Boolean);
  }, [config, sectionRules, resourceTypeId]);

  return (
    <CustomFields
      key={`custom-fields-${resourceTypeId || "none"}`}
      config={filteredConfig}
      record={record}
      templateLoaders={templateLoaders}
      fieldPathPrefix={fieldPathPrefix}
      severityChecks={severityChecks}
    />
  );
}

ConditionalCustomFields.propTypes = {
  config: PropTypes.array.isRequired,
  record: PropTypes.object,
  templateLoaders: PropTypes.array,
  fieldPathPrefix: PropTypes.string,
  severityChecks: PropTypes.object,
  sectionRules: PropTypes.object,
};

ConditionalCustomFields.defaultProps = {
  sectionRules: {},
};

export default ConditionalCustomFields;
