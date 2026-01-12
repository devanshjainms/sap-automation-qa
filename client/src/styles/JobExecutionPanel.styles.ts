// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * JobExecutionPanel Styles
 * Fluent UI makeStyles for the JobExecutionPanel component.
 */

import { makeStyles, tokens } from "@fluentui/react-components";

export const useStyles = makeStyles({
  container: {
    backgroundColor: tokens.colorNeutralBackground3,
    borderTop: `1px solid ${tokens.colorNeutralStroke2}`,
    padding: tokens.spacingVerticalM,
    height: "100%",
    overflowY: "auto",
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
  filterRow: {
    display: "flex",
    gap: tokens.spacingHorizontalS,
    marginBottom: tokens.spacingVerticalM,
    alignItems: "center",
    flexWrap: "wrap",
  },
  filterDropdown: {
    minWidth: "180px",
  },
  testList: {
    display: "flex",
    flexDirection: "column",
    gap: tokens.spacingVerticalXS,
  },
  testItem: {
    display: "flex",
    flexDirection: "column",
    backgroundColor: tokens.colorNeutralBackground1,
    borderRadius: tokens.borderRadiusMedium,
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    overflow: "hidden",
  },
  testItemHeader: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalS,
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalM}`,
    cursor: "pointer",
    ":hover": {
      backgroundColor: tokens.colorNeutralBackground1Hover,
    },
  },
  testItemExpanded: {
    borderLeft: `3px solid ${tokens.colorBrandStroke1}`,
  },
  testInfo: {
    flex: 1,
    minWidth: 0,
    display: "flex",
    flexDirection: "column",
    gap: tokens.spacingVerticalXXS,
  },
  testName: {
    fontWeight: tokens.fontWeightSemibold,
    fontSize: tokens.fontSizeBase200,
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalXS,
  },
  testDescription: {
    fontSize: tokens.fontSizeBase100,
    color: tokens.colorNeutralForeground3,
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  metaRow: {
    display: "flex",
    gap: tokens.spacingHorizontalM,
    fontSize: tokens.fontSizeBase100,
    color: tokens.colorNeutralForeground3,
  },
  metaItem: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalXXS,
  },
  statusIcon: {
    fontSize: "20px",
    display: "flex",
    alignItems: "center",
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
  expandedContent: {
    backgroundColor: tokens.colorNeutralBackground2,
    padding: tokens.spacingVerticalM,
    borderTop: `1px solid ${tokens.colorNeutralStroke2}`,
  },
  detailSection: {
    marginBottom: tokens.spacingVerticalM,
    ":last-child": {
      marginBottom: 0,
    },
  },
  detailLabel: {
    fontWeight: tokens.fontWeightSemibold,
    fontSize: tokens.fontSizeBase200,
    marginBottom: tokens.spacingVerticalXS,
    color: tokens.colorNeutralForeground1,
  },
  detailValue: {
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground2,
    wordBreak: "break-word",
  },
  outputBox: {
    fontFamily: tokens.fontFamilyMonospace,
    fontSize: tokens.fontSizeBase100,
    backgroundColor: tokens.colorNeutralBackground4,
    padding: tokens.spacingVerticalS,
    borderRadius: tokens.borderRadiusMedium,
    maxHeight: "200px",
    overflowY: "auto",
    whiteSpace: "pre-wrap",
    wordBreak: "break-all",
    border: `1px solid ${tokens.colorNeutralStroke2}`,
  },
  outputEmpty: {
    color: tokens.colorNeutralForeground3,
    fontStyle: "italic",
  },
  emptyState: {
    textAlign: "center" as const,
    color: tokens.colorNeutralForeground3,
    padding: tokens.spacingVerticalL,
  },
  progressContainer: {
    marginBottom: tokens.spacingVerticalS,
  },
  expandIcon: {
    transition: "transform 0.2s ease",
    fontSize: "16px",
  },
  expandIconExpanded: {
    transform: "rotate(90deg)",
  },
  pagination: {
    display: "flex",
    justifyContent: "center",
    alignItems: "center",
    gap: tokens.spacingHorizontalS,
    marginTop: tokens.spacingVerticalM,
    paddingTop: tokens.spacingVerticalS,
    borderTop: `1px solid ${tokens.colorNeutralStroke2}`,
  },
  nodeTag: {
    backgroundColor: tokens.colorNeutralBackground4,
    padding: `${tokens.spacingVerticalXXS} ${tokens.spacingHorizontalS}`,
    borderRadius: tokens.borderRadiusSmall,
    fontSize: tokens.fontSizeBase100,
  },
});
