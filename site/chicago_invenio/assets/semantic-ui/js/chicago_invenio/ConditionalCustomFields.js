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

  console.log('ConditionalCustomFields render - _selectedResourceType:', values?._selectedResourceType);
  console.log('ConditionalCustomFields render - config:', config);
  console.log('ConditionalCustomFields render - sectionRules:', sectionRules);

  const filterSections = () => {
    const selectedResourceType = values?._selectedResourceType;
    
    if (!selectedResourceType || Object.keys(sectionRules).length === 0) {
      // If no resource type selected or no rules defined, show all sections
      return config;
    }

    const resourceTypeId = selectedResourceType.id;
    console.log('Filtering sections for resource type:', resourceTypeId);

    return config.map(section => {
      const sectionName = section.section;
      console.log('Processing section:', sectionName);

      // Check if there's a rule for this section
      if (sectionRules[sectionName]) {
        const rule = sectionRules[sectionName];
        
        // If section has field-level rules, filter the fields
        if (rule.fieldRules) {
          console.log('Applying field-level rules for section:', sectionName);
          const filteredFields = section.fields.filter(field => {
            const fieldName = field.field;
            
            if (rule.fieldRules[fieldName]) {
              const fieldRule = rule.fieldRules[fieldName];
              
              if (fieldRule.showFor && Array.isArray(fieldRule.showFor)) {
                const shouldShow = fieldRule.showFor.includes(resourceTypeId);
                console.log(`Field "${fieldName}": showFor ${fieldRule.showFor}, current type: ${resourceTypeId}, shouldShow: ${shouldShow}`);
                return shouldShow;
              }
              
              if (fieldRule.hideFor && Array.isArray(fieldRule.hideFor)) {
                const shouldHide = fieldRule.hideFor.includes(resourceTypeId);
                console.log(`Field "${fieldName}": hideFor ${fieldRule.hideFor}, current type: ${resourceTypeId}, shouldHide: ${shouldHide}`);
                return !shouldHide;
              }
            }
            
            // If no rule for this field, show it by default
            console.log(`Field "${fieldName}": no rule, showing by default`);
            return true;
          });
          
          console.log(`Section "${sectionName}": ${filteredFields.length} fields remaining after filtering`);
          
          // If no fields remain, hide the entire section
          if (filteredFields.length === 0) {
            console.log(`Section "${sectionName}": hiding section because no fields remain`);
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
          console.log(`Section "${sectionName}": showFor ${rule.showFor}, current type: ${resourceTypeId}, shouldShow: ${shouldShow}`);
          return shouldShow ? section : null;
        }
        
        if (rule.hideFor && Array.isArray(rule.hideFor)) {
          const shouldHide = rule.hideFor.includes(resourceTypeId);
          console.log(`Section "${sectionName}": hideFor ${rule.hideFor}, current type: ${resourceTypeId}, shouldHide: ${shouldHide}`);
          return shouldHide ? null : section;
        }
      }

      // If no rule applies to this section, show it by default
      console.log(`Section "${sectionName}": no rule, showing by default`);
      return section;
    }).filter(section => section !== null); // Remove null sections
  };

  const filteredConfig = filterSections();
  console.log('Filtered config:', filteredConfig);
  console.log('Original config length:', config.length);
  console.log('Filtered config length:', filteredConfig.length);
  
  // Log each section in filtered config
  filteredConfig.forEach((section, index) => {
    console.log(`Filtered section ${index}:`, section.section, 'fields:', section.fields?.length || 0);
  });

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