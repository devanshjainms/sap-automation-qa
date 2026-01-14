// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Conversation Section Styles
 */

import { makeStyles, tokens, shorthands } from "@fluentui/react-components";

export const useStyles = makeStyles({
  section: {
    display: "flex",
    flexDirection: "column",
    flex: "0 0 auto",
    maxHeight: "none",
    overflow: "hidden",
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
  searchContainer: {
    ...shorthands.padding(tokens.spacingVerticalXS, tokens.spacingHorizontalM),
  },
  searchInput: {
    width: "100%",
  },
  list: {
    overflow: "auto",
    ...shorthands.padding("0", tokens.spacingHorizontalS),
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
  conversationItem: {
    display: "flex",
    alignItems: "center",
    ...shorthands.gap(tokens.spacingHorizontalS),
    ...shorthands.padding(tokens.spacingVerticalS, tokens.spacingHorizontalS),
    ...shorthands.margin(tokens.spacingVerticalXXS, "0"),
    ...shorthands.borderRadius(tokens.borderRadiusMedium),
    cursor: "pointer",
    position: "relative",
    minHeight: "44px",
    ":hover": {
      backgroundColor: tokens.colorNeutralBackground3Hover,
      "& .conversation-actions": {
        opacity: 1,
      },
    },
  },
  conversationItemActive: {
    backgroundColor: tokens.colorNeutralBackground3Selected,
  },
  conversationIcon: {
    fontSize: "16px",
    color: tokens.colorNeutralForeground2,
    flexShrink: 0,
  },
  conversationContent: {
    flex: 1,
    minWidth: 0,
    display: "flex",
    flexDirection: "column",
    ...shorthands.gap("2px"),
  },
  conversationTitle: {
    fontSize: tokens.fontSizeBase200,
    fontWeight: tokens.fontWeightRegular,
    color: tokens.colorNeutralForeground1,
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  conversationTime: {
    fontSize: tokens.fontSizeBase100,
    color: tokens.colorNeutralForeground3,
  },
  conversationActions: {
    opacity: 0,
    transition: "opacity 0.2s",
  },
  showMoreContainer: {
    display: "flex",
    justifyContent: "center",
    ...shorthands.padding(tokens.spacingVerticalS, tokens.spacingHorizontalM),
  },
  showMoreButton: {
    color: tokens.colorNeutralForeground2,
    ":hover": {
      color: tokens.colorNeutralForeground1,
      backgroundColor: tokens.colorNeutralBackground3Hover,
    },
  },
});
