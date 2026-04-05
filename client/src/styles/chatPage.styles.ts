// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { makeStyles, tokens } from "@fluentui/react-components";

export const useStyles = makeStyles({
  page: {
    display: "flex",
    flexDirection: "column",
    height: "100%",
    overflow: "hidden",
  },
  chatArea: {
    flex: "1",
    overflowY: "auto",
    display: "flex",
    flexDirection: "column",
  },
  /* Welcome hero */
  welcome: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    flex: "1",
    padding: `${tokens.spacingVerticalXXXL} ${tokens.spacingHorizontalL}`,
    textAlign: "center",
  },
  heroTitle: {
    fontSize: tokens.fontSizeHero800,
    fontWeight: tokens.fontWeightBold,
    color: tokens.colorNeutralForeground1,
    margin: `0 0 ${tokens.spacingVerticalS}`,
    lineHeight: tokens.lineHeightHero800,
  },
  heroSubtitle: {
    fontSize: tokens.fontSizeBase400,
    color: tokens.colorNeutralForeground3,
    margin: `0 0 ${tokens.spacingVerticalXXL}`,
  },
  suggestions: {
    display: "grid",
    gridTemplateColumns: "repeat(2, 1fr)",
    gap: tokens.spacingHorizontalM,
    maxWidth: "540px",
    width: "100%",
  },
  suggestionCard: {
    cursor: "pointer",
    textAlign: "left",
    transitionProperty: "box-shadow",
    transitionDuration: "150ms",
    ":hover": {
      boxShadow: tokens.shadow8,
    },
  },
  suggestionCardDisabled: {
    opacity: 0.5,
    cursor: "not-allowed",
  },
  /* Messages */
  messages: {
    display: "flex",
    flexDirection: "column",
    gap: tokens.spacingVerticalM,
    maxWidth: "720px",
    width: "100%",
    margin: "0 auto",
    padding: `${tokens.spacingVerticalXL} ${tokens.spacingHorizontalL}`,
  },
  userBubble: {
    alignSelf: "flex-end",
    maxWidth: "85%",
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalM}`,
    borderRadius: tokens.borderRadiusMedium,
    backgroundColor: tokens.colorBrandBackground,
    color: tokens.colorNeutralForegroundOnBrand,
    fontSize: tokens.fontSizeBase300,
    lineHeight: tokens.lineHeightBase300,
  },
  assistantBlock: {
    alignSelf: "flex-start",
    maxWidth: "85%",
    color: tokens.colorNeutralForeground1,
    fontSize: tokens.fontSizeBase300,
    lineHeight: tokens.lineHeightBase300,
    display: "flex",
    flexDirection: "column",
    gap: tokens.spacingVerticalXS,
  },
  partText: {
    overflowWrap: "break-word",
    "& p": {
      margin: `${tokens.spacingVerticalXS} 0`,
    },
    "& p:first-child": {
      marginTop: 0,
    },
    "& p:last-child": {
      marginBottom: 0,
    },
    "& strong": {
      fontWeight: tokens.fontWeightSemibold,
    },
    "& ul, & ol": {
      margin: `${tokens.spacingVerticalXS} 0`,
      paddingLeft: "20px",
    },
    "& li": {
      marginBottom: "2px",
    },
    "& code": {
      fontFamily: "Consolas, 'Courier New', monospace",
      fontSize: "0.9em",
      backgroundColor: tokens.colorNeutralBackground4,
      padding: "1px 4px",
      borderRadius: tokens.borderRadiusSmall,
    },
    "& pre": {
      backgroundColor: tokens.colorNeutralBackground4,
      padding: "8px 10px",
      borderRadius: tokens.borderRadiusMedium,
      overflow: "auto",
      fontSize: tokens.fontSizeBase200,
      margin: `${tokens.spacingVerticalS} 0`,
    },
    "& pre code": {
      backgroundColor: "transparent",
      padding: 0,
    },
    "& h1, & h2, & h3": {
      margin: `${tokens.spacingVerticalS} 0 ${tokens.spacingVerticalXS}`,
      fontWeight: tokens.fontWeightSemibold,
    },
    "& h1": { fontSize: tokens.fontSizeBase500 },
    "& h2": { fontSize: tokens.fontSizeBase400 },
    "& h3": { fontSize: tokens.fontSizeBase300 },
    "& blockquote": {
      borderLeft: `3px solid ${tokens.colorNeutralStroke2}`,
      margin: `${tokens.spacingVerticalXS} 0`,
      paddingLeft: tokens.spacingHorizontalM,
      color: tokens.colorNeutralForeground3,
    },
    "& table": {
      borderCollapse: "collapse" as const,
      fontSize: tokens.fontSizeBase200,
      margin: `${tokens.spacingVerticalS} 0`,
    },
    "& th, & td": {
      border: `1px solid ${tokens.colorNeutralStroke2}`,
      padding: "4px 8px",
    },
    "& th": {
      backgroundColor: tokens.colorNeutralBackground3,
      fontWeight: tokens.fontWeightSemibold,
    },
  },
  role: {
    display: "block",
    fontWeight: tokens.fontWeightSemibold,
    marginBottom: "2px",
    opacity: 0.7,
  },
  userRole: {
    opacity: 0.85,
  },
  content: {
    whiteSpace: "pre-wrap",
    overflowWrap: "break-word",
  },
  activitiesBlock: {
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground4,
    paddingLeft: tokens.spacingHorizontalM,
    marginBottom: tokens.spacingVerticalXS,
    lineHeight: "1.6",
  },
  inlineToolCall: {
    display: "inline-flex",
    alignItems: "center",
    gap: "5px",
    padding: "3px 10px 3px 8px",
    borderRadius: "999px",
    backgroundColor: "transparent",
    color: tokens.colorNeutralForeground4,
    fontSize: tokens.fontSizeBase200,
    lineHeight: tokens.lineHeightBase200,
    cursor: "pointer",
    userSelect: "none" as const,
    transitionProperty: "background-color",
    transitionDuration: "120ms",
    ":hover": {
      backgroundColor: tokens.colorNeutralBackground3Hover,
    },
  },
  toolCallRow: {
    display: "inline-flex",
    alignItems: "center",
    gap: "5px",
  },
  toolCallChevron: {
    display: "inline-flex",
    alignItems: "center",
    color: tokens.colorNeutralForeground4,
    flexShrink: 0,
    fontSize: tokens.fontSizeBase200,
  },
  toolCallRowIcon: {
    display: "inline-flex",
    alignItems: "center",
    flexShrink: 0,
    opacity: 0.7,
  },
  toolCallRowLabel: {
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap" as const,
    maxWidth: "320px",
    fontSize: tokens.fontSizeBase200,
  },
  toolCallOutput: {
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground3,
    backgroundColor: tokens.colorNeutralBackground1,
    padding: "8px 10px",
    margin: `${tokens.spacingVerticalXS} 0 0 0`,
    maxHeight: "180px",
    overflow: "auto",
    whiteSpace: "pre-wrap" as const,
    wordBreak: "break-word" as const,
    borderRadius: tokens.borderRadiusMedium,
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    fontFamily: "Consolas, 'Courier New', monospace",
  },
  activitiesDisclosure: {
    marginBottom: tokens.spacingVerticalS,
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground4,
  },
  activitiesSummary: {
    cursor: "pointer",
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground4,
    paddingBottom: tokens.spacingVerticalXS,
    ":hover": {
      color: tokens.colorNeutralForeground1,
    },
  },
  activitiesList: {
    marginBottom: tokens.spacingVerticalS,
    lineHeight: "1.6",
  },
  activityItem: {
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground4,
  },
  thinkingRow: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalS,
    paddingTop: tokens.spacingVerticalXS,
    paddingBottom: tokens.spacingVerticalXS,
    color: tokens.colorNeutralForeground4,
    fontStyle: "italic",
    fontSize: tokens.fontSizeBase200,
    animationName: {
      from: { opacity: 0.4 },
      to: { opacity: 1 },
    },
    animationDuration: "1.2s",
    animationIterationCount: "infinite",
    animationDirection: "alternate",
    animationTimingFunction: "ease-in-out",
  },
  spinnerRow: {
    display: "flex",
    paddingTop: tokens.spacingVerticalXS,
    paddingBottom: tokens.spacingVerticalXS,
  },
  /* Input bar */
  inputBar: {
    flexShrink: 0,
    borderTop: `1px solid ${tokens.colorNeutralStroke2}`,
    padding: `${tokens.spacingVerticalM} ${tokens.spacingHorizontalL}`,
    backgroundColor: tokens.colorNeutralBackground1,
  },
  inputInner: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalS,
    maxWidth: "720px",
    margin: "0 auto",
  },
  input: {
    flex: "1",
  },
});
