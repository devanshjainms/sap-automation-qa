// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Collapsible Sidebar Styles
 */

import { makeStyles, tokens, shorthands } from "@fluentui/react-components";

export const useStyles = makeStyles({
  container: {
    display: "flex",
    flexDirection: "column",
    width: "260px",
    height: "100%",
    backgroundColor: tokens.colorNeutralBackground2,
    borderRight: `1px solid ${tokens.colorNeutralStroke1}`,
    transition: "width 0.2s ease",
    overflow: "hidden",
  },
  containerCollapsed: {
    width: "48px",
  },
  topNav: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    ...shorthands.padding(tokens.spacingVerticalM, tokens.spacingHorizontalM),
    borderBottom: `1px solid ${tokens.colorNeutralStroke2}`,
  },
  navButton: {
    minWidth: "32px",
    height: "32px",
  },
  sectionsContainer: {
    flex: 1,
    overflow: "auto",
    display: "flex",
    flexDirection: "column",
    ...shorthands.padding(tokens.spacingVerticalS, "0"),
  },
});
