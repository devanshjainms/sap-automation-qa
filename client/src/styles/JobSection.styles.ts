// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Job Section Styles
 */

import { makeStyles, tokens, shorthands } from "@fluentui/react-components";

export const useStyles = makeStyles({
  section: {
    display: "flex",
    flexDirection: "column",
    flex: "0 0 auto",
  },
  sectionHeader: {
    display: "flex",
    alignItems: "center",
    ...shorthands.gap(tokens.spacingHorizontalXS),
    ...shorthands.padding(tokens.spacingVerticalS, tokens.spacingHorizontalM),
    cursor: "pointer",
    userSelect: "none",
    minHeight: "40px",
    ":hover": {
      backgroundColor: tokens.colorNeutralBackground3Hover,
    },
  },
  expandButton: {
    minWidth: "20px",
    ...shorthands.padding("0"),
  },
  sectionTitle: {
    flex: 1,
    fontSize: tokens.fontSizeBase300,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground1,
  },
  sectionActions: {
    display: "flex",
    ...shorthands.gap(tokens.spacingHorizontalXXS),
  },
  sectionContent: {
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
  },
  loadingContainer: {
    display: "flex",
    justifyContent: "center",
    alignItems: "center",
    ...shorthands.padding(tokens.spacingVerticalXL),
  },
  emptyState: {
    display: "flex",
    justifyContent: "center",
    alignItems: "center",
    ...shorthands.padding(tokens.spacingVerticalXL, tokens.spacingHorizontalM),
    color: tokens.colorNeutralForeground3,
    fontSize: tokens.fontSizeBase200,
    textAlign: "center",
  },
  list: {
    overflow: "auto",
    ...shorthands.padding("0", tokens.spacingHorizontalS),
  },
  jobItem: {
    display: "flex",
    alignItems: "center",
    ...shorthands.gap(tokens.spacingHorizontalS),
    ...shorthands.padding(tokens.spacingVerticalS, tokens.spacingHorizontalS),
    ...shorthands.margin(tokens.spacingVerticalXXS, "0"),
    ...shorthands.borderRadius(tokens.borderRadiusMedium),
    cursor: "pointer",
    minHeight: "44px",
    ":hover": {
      backgroundColor: tokens.colorNeutralBackground3Hover,
    },
  },
  jobIcon: {
    fontSize: "16px",
    color: tokens.colorNeutralForeground2,
    flexShrink: 0,
  },
  jobContent: {
    flex: 1,
    minWidth: 0,
    display: "flex",
    flexDirection: "column",
    ...shorthands.gap("2px"),
  },
  jobTitle: {
    fontSize: tokens.fontSizeBase200,
    fontWeight: tokens.fontWeightRegular,
    color: tokens.colorNeutralForeground1,
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  jobSubtitle: {
    fontSize: tokens.fontSizeBase100,
    color: tokens.colorNeutralForeground3,
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  jobText: {
    fontSize: tokens.fontSizeBase200,
  },
});
