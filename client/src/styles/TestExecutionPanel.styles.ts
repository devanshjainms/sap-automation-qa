// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * TestExecutionPanel Styles
 * Fluent UI makeStyles for the TestExecutionPanel component.
 */

import { makeStyles, tokens } from "@fluentui/react-components";

export const useStyles = makeStyles({
  container: {
    backgroundColor: tokens.colorNeutralBackground3,
    borderTop: `1px solid ${tokens.colorNeutralStroke2}`,
    padding: tokens.spacingVerticalM,
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: tokens.spacingVerticalS,
  },
  headerActions: {
    display: "flex",
    gap: "8px",
    alignItems: "center",
  },
  title: {
    fontWeight: tokens.fontWeightSemibold,
    fontSize: tokens.fontSizeBase300,
  },
  testList: {
    display: "flex",
    flexDirection: "column",
    gap: tokens.spacingVerticalS,
  },
  testItem: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalS,
    padding: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalS}`,
    backgroundColor: tokens.colorNeutralBackground1,
    borderRadius: tokens.borderRadiusMedium,
  },
  testInfo: {
    flex: 1,
    minWidth: 0,
  },
  testName: {
    fontWeight: tokens.fontWeightSemibold,
    fontSize: tokens.fontSizeBase200,
  },
  testDescription: {
    fontSize: tokens.fontSizeBase100,
    color: tokens.colorNeutralForeground3,
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  statusIcon: {
    fontSize: "20px",
  },
  running: {
    color: tokens.colorBrandForeground1,
  },
  completed: {
    color: tokens.colorPaletteGreenForeground1,
  },
  failed: {
    color: tokens.colorPaletteRedForeground1,
  },
  pending: {
    color: tokens.colorNeutralForeground3,
  },
  emptyState: {
    textAlign: "center" as const,
    color: tokens.colorNeutralForeground3,
    padding: tokens.spacingVerticalM,
  },
  progressContainer: {
    marginTop: tokens.spacingVerticalXS,
  },
});
