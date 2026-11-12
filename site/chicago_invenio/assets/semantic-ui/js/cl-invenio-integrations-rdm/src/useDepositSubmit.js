import { useContext } from "react";
import { useFormikContext } from "formik";

import {
  DepositFormSubmitActions,
  DepositFormSubmitContext,
} from "./Components";

export const useDepositSubmit = () => {
  const { setSubmitContext } = useContext(DepositFormSubmitContext);
  const { submitForm } = useFormikContext();

  const saveDraft = () => {
    setSubmitContext(DepositFormSubmitActions.SAVE);
    return submitForm();
  };

  return { saveDraft };
};