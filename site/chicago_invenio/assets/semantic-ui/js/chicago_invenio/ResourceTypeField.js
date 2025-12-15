// ResourceTypeField.js
import React, { Component } from "react";
import PropTypes from "prop-types";
import _get from "lodash/get";
import { FieldLabel, SelectField } from "react-invenio-forms";
import { i18next } from "@translations/invenio_rdm_records/i18next";

export class ResourceTypeField extends Component {
  groupErrors = (errors, fieldPath) => {
    const fieldErrors = _get(errors, fieldPath);
    if (fieldErrors) {
      return { content: fieldErrors };
    }
    return null;
  };

  _label = (option) => {
    return option.type_name + (option.subtype_name ? " / " + option.subtype_name : "");
  };

  createOptions = (propsOptions = []) => {
    return propsOptions
      .map((o) => ({ ...o, label: this._label(o) }))
      .sort((o1, o2) => o1.label.localeCompare(o2.label))
      .map((o) => {
        return {
          value: o.id,
          icon: o.icon,
          text: o.label,
        };
      });
  };

  handleChange = ({ event, data, formikProps }) => {
    const value = data?.value;
    const { options, fieldPath } = this.props;
    const selectedOption = options?.find(o => o.id === value) || null;
    
    if (formikProps?.form) {
      const { setFieldValue } = formikProps.form;
      
      // First set the main field value (this is crucial for display)
      setFieldValue(fieldPath, value);
      
      // Then set additional Formik field values for other components to access
      if (selectedOption) {
        setFieldValue('_selectedResourceType', selectedOption);
        setFieldValue('_resourceTypeId', selectedOption.id || '');
        setFieldValue('_resourceTypeName', selectedOption.type_name || '');
        setFieldValue('_resourceTypeSubtype', selectedOption.subtype_name || '');
        
        //console.log('Selected resource type:', selectedOption);
        //console.log(fieldPath);
      }
    }
  };

  render() {
    const { fieldPath, label, labelIcon, options, ...restProps } = this.props;
    const frontEndOptions = this.createOptions(options);
    return (
      <SelectField
        fieldPath={fieldPath}
        label={<FieldLabel htmlFor={fieldPath} icon={labelIcon} label={label} />}
        optimized
        aria-label={label}
        options={frontEndOptions}
        //helpText={i18next.t("Select the resource type that best describes your resource.")}
        selectOnBlur={false}
        onChange={this.handleChange}
        {...restProps}
      />
    );
  }
}

ResourceTypeField.propTypes = {
  fieldPath: PropTypes.string.isRequired,
  label: PropTypes.string,
  labelIcon: PropTypes.string,
  labelclassname: PropTypes.string,
  options: PropTypes.arrayOf(
    PropTypes.shape({
      icon: PropTypes.string,
      type_name: PropTypes.string,
      subtype_name: PropTypes.string,
      id: PropTypes.string,
    })
  ).isRequired,
  required: PropTypes.bool,
  onChange: PropTypes.func, // receives (value, selectedOption, event)
};

ResourceTypeField.defaultProps = {
  label: i18next.t("Resource type"),
  labelIcon: "tag",
  labelclassname: "field-label-class",
  required: false,
  //onChange: undefined,
};

export default ResourceTypeField;