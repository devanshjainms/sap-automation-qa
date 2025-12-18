// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * ConversationSidebar Styles
 * Fluent UI makeStyles for the ConversationSidebar component.
 */

import { makeStyles, tokens } from "@fluentui/react-components";

export const useStyles = makeStyles({
  container: {
    display: "flex",
    flexDirection: "column",
    height: "100%",
    backgroundColor: tokens.colorNeutralBackground2,
    borderRight: `1px solid ${tokens.colorNeutralStroke2}`,
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: `${tokens.spacingVerticalM} ${tokens.spacingHorizontalM}`,
    borderBottom: `1px solid ${tokens.colorNeutralStroke2}`,
  },
  headerTitle: {
    fontWeight: tokens.fontWeightSemibold,
    fontSize: tokens.fontSizeBase400,
  },
  list: {
    flex: 1,
    overflowY: "auto",
    padding: tokens.spacingVerticalS,
  },
  emptyState: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    height: "100px",
    color: tokens.colorNeutralForeground3,
    fontSize: tokens.fontSizeBase200,
  },
  conversationItem: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalS,
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalM}`,
    borderRadius: tokens.borderRadiusMedium,
    cursor: "pointer",
    transition: "background-color 0.1s",
    ":hover": {
      backgroundColor: tokens.colorNeutralBackground1Hover,
    },
    ":hover .conversation-actions": {
      opacity: 1,
    },
  },
  conversationItemActive: {
    backgroundColor: tokens.colorNeutralBackground1Selected,
  },
  conversationIcon: {
    color: tokens.colorNeutralForeground2,
    flexShrink: 0,
  },
  conversationContent: {
    flex: 1,
    minWidth: 0,
    overflow: "hidden",
  },
  conversationTitle: {
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
    fontSize: tokens.fontSizeBase200,
  },
  conversationTime: {
    fontSize: tokens.fontSizeBase100,
    color: tokens.colorNeutralForeground3,
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  conversationActions: {
    opacity: 0,
    transition: "opacity 0.2s",
    flexShrink: 0,
  },
  loadingContainer: {
    display: "flex",
    justifyContent: "center",
    padding: tokens.spacingVerticalL,
  },
});
