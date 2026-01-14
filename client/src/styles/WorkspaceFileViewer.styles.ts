// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Workspace File Viewer Styles
 */

import { makeStyles, tokens, shorthands } from "@fluentui/react-components";

export const useStyles = makeStyles({
  container: {
    display: "flex",
    flexDirection: "column",
    height: "100vh",
    backgroundColor: tokens.colorNeutralBackground1,
    maxWidth: "900px",
    margin: "0 auto",
    width: "100%",
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: tokens.spacingVerticalM,
    borderBottom: `1px solid ${tokens.colorNeutralStroke1}`,
    backgroundColor: tokens.colorNeutralBackground2,
  },
  headerLeft: {
    display: "flex",
    flexDirection: "column",
    gap: "4px",
  },
  headerRight: {
    display: "flex",
    gap: tokens.spacingHorizontalS,
    alignItems: "center",
  },
  title: {
    fontSize: tokens.fontSizeBase400,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground1,
  },
  subtitle: {
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground3,
  },
  content: {
    flex: 1,
    overflow: "auto",
    display: "flex",
    flexDirection: "column",
  },
  loadingContainer: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    gap: tokens.spacingVerticalM,
    height: "100%",
  },
  errorContainer: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    gap: tokens.spacingVerticalM,
    height: "100%",
    padding: tokens.spacingHorizontalXL,
  },
  errorText: {
    color: tokens.colorPaletteRedForeground1,
    textAlign: "center",
  },
  editor: {
    flex: 1,
    maxHeight: "none !important",
    height: "100% !important",
    fontFamily: "Consolas, 'Courier New', monospace",
    fontSize: tokens.fontSizeBase300,
    ...shorthands.padding(tokens.spacingVerticalL),
    ...shorthands.border("1px", "solid", tokens.colorNeutralStroke1),
    ...shorthands.borderRadius(tokens.borderRadiusMedium),
    ...shorthands.margin(tokens.spacingVerticalM, tokens.spacingHorizontalL),
    resize: "none",
    backgroundColor: tokens.colorNeutralBackground1,
    ":focus": {
      ...shorthands.outline("2px", "solid", tokens.colorBrandStroke1),
    },
  },
  footer: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: tokens.spacingVerticalS,
    borderTop: `1px solid ${tokens.colorNeutralStroke1}`,
    backgroundColor: tokens.colorPaletteYellowBackground2,
  },
  footerText: {
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground2,
  },
});
