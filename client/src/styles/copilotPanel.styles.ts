// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { makeStyles, tokens } from "@fluentui/react-components";

export const useStyles = makeStyles({
  panel: {
    display: "flex",
    flexDirection: "column",
    height: "100%",
    backgroundColor: tokens.colorNeutralBackground1,
  },
  header: {
    padding: `${tokens.spacingVerticalM} ${tokens.spacingHorizontalL}`,
    borderBottom: `1px solid ${tokens.colorNeutralStroke2}`,
    flexShrink: 0,
  },
  messages: {
    flex: "1",
    overflowY: "auto",
    padding: `${tokens.spacingVerticalM} ${tokens.spacingHorizontalL}`,
    display: "flex",
    flexDirection: "column",
    gap: tokens.spacingVerticalM,
  },
  welcome: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    height: "100%",
    padding: "2rem",
    textAlign: "center",
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
  assistantBubble: {
    alignSelf: "flex-start",
    maxWidth: "85%",
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalM}`,
    borderRadius: tokens.borderRadiusMedium,
    backgroundColor: tokens.colorNeutralBackground3,
    color: tokens.colorNeutralForeground1,
    fontSize: tokens.fontSizeBase300,
    lineHeight: tokens.lineHeightBase300,
  },
  role: {
    display: "block",
    fontWeight: tokens.fontWeightSemibold,
    marginBottom: "2px",
    opacity: 0.7,
  },
  userRole: { opacity: 0.85 },
  content: {
    whiteSpace: "pre-wrap",
    overflowWrap: "break-word",
  },
  activitiesDisclosure: {
    marginBottom: tokens.spacingVerticalXS,
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
    marginBottom: tokens.spacingVerticalXS,
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
  },
  inputRow: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalS,
    padding: `${tokens.spacingVerticalM} ${tokens.spacingHorizontalL}`,
    borderTop: `1px solid ${tokens.colorNeutralStroke2}`,
    flexShrink: 0,
  },
  input: { flex: "1" },
});
