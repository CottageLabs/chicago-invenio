// This file is part of InvenioRDM
// Copyright (C) 2023 CERN.
//
// Invenio App RDM is free software; you can redistribute it and/or modify it
// under the terms of the MIT License; see LICENSE file for more details.

/**
 * Add here all the overridden components of your app.
 */

import {ResourceTypeField} from "../../chicago_invenio/ResourceTypeField";
import {ConditionalCustomFields} from "../../chicago_invenio/ConditionalCustomFields";
import { parametrize } from "react-overridable";
import { curationComponentOverrides } from "@js/invenio_curations/requests";
import { DepositBox } from "@js/invenio_curations/deposit/DepositBox";
import buildConfig from "../../chicago_invenio/build_config.json";

const ConditionalCustomFieldsWithRules = parametrize(ConditionalCustomFields, {
    sectionRules: {
        "Publishing information": {
            showFor: ['publication-thesis', 'publication-article', 'publication-section', 'publication-book', 'publication-journal'],
            fieldRules: {
                // Thesis fields - only show for thesis publications
                "thesis:thesis": { showFor: ['publication-thesis'] },
                // Journal fields - only show for specific publication types
                "journal:journal": { showFor: ['publication-article', 'publication-journal'] },
                // Imprint fields - only show for specific publication types
                "imprint:imprint": { showFor: ['publication-section', 'publication-book'] }
            }
        },
        "Conference": {
            showFor: ['publication-conferenceproceeding', 'publication-conferencepaper']
        },
        // University of Chicago Information section will show for all types (no rule)
    }
});

export const overriddenComponents = {
    ...(buildConfig.enableCurations ? curationComponentOverrides : {}),
    ...(buildConfig.enableCurations ? {"InvenioAppRdm.Deposit.CardDepositStatusBox.container": DepositBox} : {}),
    "InvenioAppRdm.Deposit.ResourceTypeField.container": ResourceTypeField,
    "InvenioAppRdm.Deposit.CustomFields.container": ConditionalCustomFieldsWithRules,
}
