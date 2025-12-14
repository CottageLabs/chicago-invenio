// This file is part of InvenioRDM
// Copyright (C) 2023 CERN.
//
// Invenio App RDM is free software; you can redistribute it and/or modify it
// under the terms of the MIT License; see LICENSE file for more details.

/**
 * Add here all the overridden components of your app.
 */

import { HiddenField } from "../../chicago_invenio/HiddenField";
import {
    ResourceTypeField
} from "../../chicago_invenio/ResourceTypeField";
import {VersionField} from "../../chicago_invenio/VersionField";
import {RDMDepositForm} from "../../chicago_invenio/RDMDepositForm";
import {ConditionalCustomFields} from "../../chicago_invenio/ConditionalCustomFields";
import { parametrize } from "react-overridable";

const ConditionalVersionField = parametrize(VersionField, {
    showWhenResourceTypes: ['software', 'dataset', 'event']
});

const ConditionalCustomFieldsWithRules = parametrize(ConditionalCustomFields, {
    sectionRules: {
        "Publishing information": {
            fieldRules: {
                // Thesis fields - only show for thesis publications
                "thesis:thesis": { showFor: ['publication-thesis'] },
                // Journal fields - hide for thesis, dataset, software
                "journal:journal": { hideFor: ['publication-thesis', 'dataset', 'software'] },
                // Imprint fields - hide for thesis, dataset, software  
                "imprint:imprint": { hideFor: ['publication-thesis', 'dataset', 'software'] }
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
