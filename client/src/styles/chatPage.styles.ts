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
  userRole: {
    opacity: 0.85,
  },
  content: {
    whiteSpace: "pre-wrap",
    overflowWrap: "break-word",
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
