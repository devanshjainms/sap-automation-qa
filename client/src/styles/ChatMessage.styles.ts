// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * ChatMessage Styles
 * Fluent UI makeStyles for the ChatMessage component.
 */

import { makeStyles, tokens } from "@fluentui/react-components";

export const useStyles = makeStyles({
  messageContainer: {
    display: "flex",
    gap: tokens.spacingHorizontalM,
    padding: tokens.spacingVerticalM,
    maxWidth: "900px",
    margin: "0 auto",
  },
  userMessage: {
    flexDirection: "row-reverse",
  },
  avatar: {
    width: "32px",
    height: "32px",
    borderRadius: tokens.borderRadiusCircular,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
  },
  userAvatar: {
    backgroundColor: tokens.colorBrandBackground,
    color: tokens.colorNeutralForegroundOnBrand,
  },
  assistantAvatar: {
    backgroundColor: tokens.colorNeutralBackground3,
    color: tokens.colorBrandForeground1,
  },
  messageContent: {
    flex: 1,
    minWidth: 0,
  },
  messageBubble: {
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalM}`,
    borderRadius: tokens.borderRadiusMedium,
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
    lineHeight: "1.5",
  },
  userBubble: {
    backgroundColor: tokens.colorBrandBackground,
    color: tokens.colorNeutralForegroundOnBrand,
    marginLeft: "auto",
    maxWidth: "80%",
  },
  assistantBubble: {
    backgroundColor: tokens.colorNeutralBackground3,
    color: tokens.colorNeutralForeground1,
  },
  agentChain: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalXS,
    marginBottom: tokens.spacingVerticalXS,
    fontSize: tokens.fontSizeBase100,
    color: tokens.colorNeutralForeground3,
  },
  agentBadge: {
    backgroundColor: tokens.colorNeutralBackground4,
    padding: "1px 6px",
    borderRadius: tokens.borderRadiusSmall,
    fontWeight: tokens.fontWeightSemibold,
  },
  actions: {
    display: "flex",
    gap: tokens.spacingHorizontalXS,
    marginTop: tokens.spacingVerticalXS,
    opacity: 0,
    transition: "opacity 0.2s",
  },
  actionsVisible: {
    opacity: 1,
  },
  messageWrapper: {
    ":hover .message-actions": {
      opacity: 1,
    },
  },
  markdown: {
    "& p": {
      margin: "0 0 4px 0",
      "&:last-child": {
        marginBottom: 0,
      },
    },
    "& ul, & ol": {
      margin: "4px 0",
      paddingLeft: "20px",
    },
    "& li": {
      marginBottom: "2px",
      "& p": {
        margin: 0,
      },
    },
    "& code": {
      backgroundColor: tokens.colorNeutralBackground4,
      padding: "1px 4px",
      borderRadius: tokens.borderRadiusSmall,
      fontFamily: "monospace",
      fontSize: "0.9em",
    },
    "& pre": {
      backgroundColor: tokens.colorNeutralBackground4,
      padding: "8px 12px",
      borderRadius: tokens.borderRadiusMedium,
      overflow: "auto",
      margin: "4px 0",
      "& code": {
        backgroundColor: "transparent",
        padding: 0,
      },
    },
    "& strong": {
      fontWeight: 600,
    },
    "& h1, & h2, & h3, & h4": {
      margin: "8px 0 4px 0",
      fontWeight: 600,
    },
    "& h1": { fontSize: "1.2em" },
    "& h2": { fontSize: "1.15em" },
    "& h3": { fontSize: "1.1em" },
    "& blockquote": {
      borderLeft: `3px solid ${tokens.colorBrandBackground}`,
      margin: "4px 0",
      paddingLeft: "12px",
      color: tokens.colorNeutralForeground2,
    },
    "& table": {
      borderCollapse: "collapse",
      margin: "8px 0",
      width: "100%",
    },
    "& th, & td": {
      border: `1px solid ${tokens.colorNeutralStroke1}`,
      padding: "6px 10px",
      textAlign: "left" as const,
    },
    "& th": {
      backgroundColor: tokens.colorNeutralBackground3,
      fontWeight: 600,
    },
  },
});
