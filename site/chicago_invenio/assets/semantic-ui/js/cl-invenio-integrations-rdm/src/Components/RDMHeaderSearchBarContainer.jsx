// RDMHeaderSearchBarContainer.jsx

// A replacement workaround container to SearchBar
// from Invenio Search UI. That implementation forces
// innerHTML = "" on every draw, causing it to remove
// _itself_ when redrawing. Considered using
// unmountComponentAtNode, but this is React 16 specific
// and replaced by root.unmount (which we can't use)
// in React 18.
//
// A proper fix upstream should make it so one react component
// (in the same OR different tree) doesn't need to handle
// unmounting of a DOM node controlled by another component.
// For starters the "standalone" search isn't in any way
// overrideable right now, where the searchkit one is.
import { useEffect, useState } from "react";
import {
  SearchBar as ReactSearchKitSearchBar,
  buildUID,
} from "react-searchkit";
import ReactDOM from "react-dom";
import Overridable from "react-overridable";

// This is an explicit OVERRIDE fixing a bug:
export const RDMHeaderSearchBarContainer = ({
  appName,
  buildUID: uidBuilder = buildUID,
  children,
  config,
  elementId = "header-search-bar", // Allow reuse should we need it later
  // Assume any remaining props are to be passed directly to the SearchBar from RSK
  // However it's on to the Overridden SearchBar.Element to actually handle passing
  // those to the final Search input, so this is only a partial fix.
  ...searchBarProps
}) => {
  const [portalTarget, setPortalTarget] = useState(undefined);
  useEffect(() => {
    const target = document.getElementById(elementId);

    if (!target) {
      setPortalTarget(null);
      return;
    }

    // Nuke anything React has
    // mounted into the DOM ONCE, on render.
    // In theory this should remove the
    // theme.js -> SearchBar _without_ then
    // removing itself on redraw
    // (like opening the filter drawer)
    //
    // This is not ideal, ideally we'd want the
    // React trees to not be fighting over the
    // same DOM node at all, removing the need
    // for any management between react components.
    // That's out of scope here though, keep change
    // as small as possible.
    target.innerHTML = "";

    setPortalTarget(target);
  }, []);

  const searchBar = (
    <Overridable
      id={uidBuilder("SearchApp.searchbar", "", appName)}
      {...searchBarProps}
    >
      <ReactSearchKitSearchBar {...searchBarProps} />
    </Overridable>
  );

  return portalTarget
    ? ReactDOM.createPortal(searchBar, portalTarget)
    : searchBar;
};
