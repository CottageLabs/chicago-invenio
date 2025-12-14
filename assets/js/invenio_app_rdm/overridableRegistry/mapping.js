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
import { parametrize } from "react-overridable";

const ConditionalVersionField = parametrize(VersionField, {
    showWhenResourceTypes: ['software', 'dataset', 'event']
});

export const overriddenComponents = {
    "InvenioAppRdm.Deposit.ResourceTypeField.container": ResourceTypeField,
    "InvenioAppRdm.Deposit.VersionField.container": ConditionalVersionField,
    //"InvenioAppRdm.Deposit.RDMDepositForm.layout": HiddenField,
}
