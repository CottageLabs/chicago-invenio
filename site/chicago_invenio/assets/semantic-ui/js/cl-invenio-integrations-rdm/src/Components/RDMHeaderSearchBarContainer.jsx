import React, { useLayoutEffect, useState } from "react";
import { createPortal } from "react-dom";
import { SearchBar as ReactSearchKitSearchBar } from "react-searchkit";

// A replacement workaround container to SearchBar
// from Invenio Search UI. That implementation forces
// innerHTML = "" on target node, causing havoc where
// multiple React trees fight over the same node.
// Considered using unmountComponentAtNode, but this is
// React 16 specific and replaced by root.unmount
// (which we can't use) in React 18. This instead mounts
// the search onto a sibling node and hides the standalone
// one.
export const RDMHeaderSearchBarContainer = ({
  elementId = "header-search-bar",
  ...searchBarProps
}) => {
  const [portalTarget, setPortalTarget] = useState(null);

  // Using useLayoutEffect so this happens before paint
useLayoutEffect(() => {
    const standalone = document.getElementById(elementId);

    if (!standalone || !standalone.parentNode) {
      console.warn(`Missing search bar target: #${elementId}`);
      return;
    }

    const hiddenId = `${elementId}-standalone`;

    if (document.getElementById(hiddenId)) {
      console.warn(`Duplicate search bar target: #${hiddenId}`);
      return;
    }

    // Clone attributes and styling, but not React children.
    const connected = standalone.cloneNode(false);

    const display = standalone.style.getPropertyValue("display");
    const priority = standalone.style.getPropertyPriority("display");

    // Transfer the original ID to the connected search to keep styling etc etc the same'
    // Preserve the original ID for CSS and RDM's data-options lookup.
    // This assumes upstream does not require the standalone element
    // to retain its original ID after mounting...
    // This should be FIXED upstream.
    standalone.id = hiddenId;
    connected.id = elementId;

    connected.setAttribute("data-cl-searchkit-header", "");

    standalone.parentNode.insertBefore(
      connected,
      standalone.nextSibling
    );

    standalone.style.setProperty("display", "none", "important");

    setPortalTarget(connected);

    return () => {
      connected.remove();

      // Restore the original standalone search id
      standalone.id = elementId;

      if (display) {
        standalone.style.setProperty("display", display, priority);
      } else {
        standalone.style.removeProperty("display");
      }
    };
  }, [elementId]);

  return portalTarget
    ? createPortal(
        <ReactSearchKitSearchBar {...searchBarProps} />,
        portalTarget
      )
    : null;
};
