// This file is part of InvenioRDM
// Copyright (C) 2023 CERN.
//
// Invenio App RDM is free software; you can redistribute it and/or modify it
// under the terms of the MIT License; see LICENSE file for more details.

/**
 * Add here all the overridden components of your app.
 */

//import { HiddenField } from "../../chicago_invenio/HiddenField";
import {
    ResourceTypeField
} from "../../chicago_invenio/ResourceTypeField";
import {VersionField} from "../../chicago_invenio/VersionField";
//import {RDMDepositForm} from "../../chicago_invenio/RDMDepositForm";
import {ConditionalCustomFields} from "../../chicago_invenio/ConditionalCustomFields";
import { parametrize } from "react-overridable";

const ConditionalVersionField = parametrize(VersionField, {
    showWhenResourceTypes: ['software', 'dataset']
});

const ConditionalCustomFieldsWithRules = parametrize(ConditionalCustomFields, {
    sectionRules: {
        "Publishing information": {
            showFor: ['publication-thesis', 'publication-article', 'publication-section', 'publication-book'],
            fieldRules: {
                // Thesis fields - only show for thesis publications
                "thesis:thesis": { showFor: ['publication-thesis'] },
                // Journal fields - only show for specific publication types
                "journal:journal": { showFor: ['publication-article'] },
                // Imprint fields - only show for specific publication types
                "imprint:imprint": { showFor: ['publication-section', 'publication-book'] }
            }
        },
        "Meeting": {
            showFor: ['event', 'conference']
        }
        // University of Chicago Information section will show for all types (no rule)
    }
});

export const overriddenComponents = {
    "InvenioAppRdm.Deposit.ResourceTypeField.container": ResourceTypeField,
    "InvenioAppRdm.Deposit.VersionField.container": ConditionalVersionField,
    "InvenioAppRdm.Deposit.CustomFields.container": ConditionalCustomFieldsWithRules,
    //"InvenioAppRdm.Deposit.RDMDepositForm.layout": HiddenField,
}
