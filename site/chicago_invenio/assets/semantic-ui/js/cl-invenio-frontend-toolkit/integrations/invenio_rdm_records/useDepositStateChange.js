// @cl-toolkit/integrations/invenio_rdm_records/useDepositStateChange.js

import { useEffect, useRef } from "react";
import { useSelector } from "react-redux";

// Allows a downstream application to perform a side effect on change of state for a deposit record
export const useDepositStateChange = (stateChangeConfig) => {
  const actionState = useSelector(
    (state) => state.deposit?.actionState
  );

  const previousActionState = useRef(actionState);

  useEffect(() => {

    if(
      (actionState !== previousActionState) &&
      stateChangeConfig[actionState] instanceof Function
    ) {
      try {
        stateChangeConfig[actionState]()
      } catch {
        console.error(`Something went wrong running stateChangeConfig[${actionState}]`)
      }
    }
    previousActionState.current = actionState;
  }, [actionState]);
};