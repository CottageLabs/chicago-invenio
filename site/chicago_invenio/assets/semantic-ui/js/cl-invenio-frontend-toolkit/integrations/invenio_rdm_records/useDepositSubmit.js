import { useContext } from "react";
import { useFormikContext } from "formik";

// WARNING: See README#Implementation warnings for details
import {
  DepositFormSubmitActions,
  DepositFormSubmitContext,
} from "@js/invenio_rdm_records/src/deposit/api/DepositFormSubmitContext";

export const useDepositSubmit = () => {
  const { setSubmitContext } = useContext(DepositFormSubmitContext);
  const { submitForm } = useFormikContext();

  const saveDraft = () => {
    setSubmitContext(DepositFormSubmitActions.SAVE);
    return submitForm();
  };

  return { saveDraft };
};