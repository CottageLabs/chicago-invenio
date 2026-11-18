// ChicagoSearchBarContainer.jsx

import { useEffect, useState } from "react";
import {
  SearchBar as ReactSearchKitSearchBar,
  buildUID,
} from "react-searchkit";
import ReactDOM from "react-dom";
import Overridable from "react-overridable";

// This is an explicit OVERRIDE fixing a bug:
export const ChicagoSearchBarContainer = ({
  appName,
  buildUID: uidBuilder = buildUID,
  elementId = "header-search-bar" // Allow reuse should we need it later
}) => {
  const [portalTarget, setPortalTarget] = useState(null);

  useEffect(() => {
    const target = document.getElementById(elementId);

    if (!target) {
      return;
    }

    // Attempt to unmount anything React has
    // mounted into the DOM ONCE, on render.
    // In theory this should unmount the
    // theme.js -> SearchBar _without_ then
    // unmounting itself on redraw
    // (like opening the filter drawer)
    //
    // This is "more official" rather than
    // destroying the DOM node directly with innerHTML
    //
    //
    // If for any reason some non-React node was operating
    // there, we could return to target.innerHTML = ""
    // The fix is really the single-run useEffect
    ReactDOM.unmountComponentAtNode(target);

    setPortalTarget(target);
  }, []);

  if (!portalTarget) {
    return null;
  }

  return ReactDOM.createPortal(
    <Overridable id={uidBuilder("SearchApp.searchbar", "", appName)}>
      <ReactSearchKitSearchBar />
    </Overridable>,
    portalTarget
  );
};
