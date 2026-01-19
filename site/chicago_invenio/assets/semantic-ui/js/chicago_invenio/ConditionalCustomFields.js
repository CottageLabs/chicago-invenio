import React from "react";
import PropTypes from "prop-types";
import { useFormikContext } from "formik";
import { CustomFields } from "react-invenio-forms";

export function ConditionalCustomFields({ 
  config, 
  record, 
  templateLoaders, 
  fieldPathPrefix, 
  severityChecks,
  sectionRules = {}
}) {
  const { values } = useFormikContext();

  const filterSections = () => {
    const selectedResourceType = values?._selectedResourceType || { id: null };
    
    if (Object.keys(sectionRules).length === 0) {
      // If no rules defined, show all sections
      return config;
    }

    const resourceTypeId = selectedResourceType.id;

    return config.map(section => {
      const sectionName = section.section;

      // Check if there's a rule for this section
      if (sectionRules[sectionName]) {
        const rule = sectionRules[sectionName];
        
        // If section has field-level rules, filter the fields
        if (rule.fieldRules) {
          const filteredFields = section.fields.filter(field => {
            const fieldName = field.field;
            
            if (rule.fieldRules[fieldName]) {
              const fieldRule = rule.fieldRules[fieldName];
              
              if (fieldRule.showFor && Array.isArray(fieldRule.showFor)) {
                const shouldShow = fieldRule.showFor.includes(resourceTypeId);
                return shouldShow;
              }
              
              if (fieldRule.hideFor && Array.isArray(fieldRule.hideFor)) {
                const shouldHide = fieldRule.hideFor.includes(resourceTypeId);
                return !shouldHide;
              }
            }
            
            // If no rule for this field, show it by default
            return true;
          });

          // If no fields remain, hide the entire section
          if (filteredFields.length === 0) {
            return null;
          }
          
          return {
            ...section,
            fields: filteredFields
          };
        }
        
        // Section-level rules (hide entire section)
        if (rule.showFor && Array.isArray(rule.showFor)) {
          const shouldShow = rule.showFor.includes(resourceTypeId);
          return shouldShow ? section : null;
        }
        
        if (rule.hideFor && Array.isArray(rule.hideFor)) {
          const shouldHide = rule.hideFor.includes(resourceTypeId);
          return shouldHide ? null : section;
        }
      }

      // If no rule applies to this section, show it by default
      return section;
    }).filter(section => section !== null); // Remove null sections
  };

  const filteredConfig = filterSections();

  return (
    <CustomFields
      key={`custom-fields-${values?._selectedResourceType?.id || 'none'}`}
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