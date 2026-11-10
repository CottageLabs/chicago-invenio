# CL Toolkit Integrations | Invenio RDM Records
A submodule dedicated to implementing functionality needed for CL implementations of RDM records/deposits

## Implementation warnings
Some of the integrations are forced into less-than-perfect decisions because of upstream dependencies.
We demarcate those here so that we can track those in case of regressions or potentially commit upstream tweaks to make our llives (and hopefully the community's) easier.
### useDepositSubmit()
We are forced into an internal import of DepositFormSubmitContext as it is not available via ordinary export from the module.