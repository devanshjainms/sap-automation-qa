// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * ReportsPanel Styles
 * Fluent UI makeStyles for the ReportsPanel component.
 */

import { makeStyles, tokens } from "@fluentui/react-components";

export const useStyles = makeStyles({
  container: {
    display: "flex",
    flexDirection: "column",
    height: "100%",
    backgroundColor: tokens.colorNeutralBackground1,
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "16px 24px",
    borderBottom: `1px solid ${tokens.colorNeutralStroke2}`,
  },
  title: {
    fontSize: tokens.fontSizeBase500,
    fontWeight: tokens.fontWeightSemibold,
  },
  headerActions: {
    display: "flex",
    gap: "8px",
    alignItems: "center",
  },
  content: {
    flex: 1,
    display: "flex",
    overflow: "hidden",
  },
  sidebar: {
    width: "300px",
    borderRight: `1px solid ${tokens.colorNeutralStroke2}`,
    display: "flex",
    flexDirection: "column",
    backgroundColor: tokens.colorNeutralBackground2,
  },
  sidebarHeader: {
    padding: "12px 16px",
    borderBottom: `1px solid ${tokens.colorNeutralStroke2}`,
  },
  reportList: {
    flex: 1,
    overflowY: "auto",
    padding: "8px",
  },
  reportItem: {
    padding: "12px",
    marginBottom: "4px",
    borderRadius: tokens.borderRadiusMedium,
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    gap: "8px",
    transition: "background-color 0.2s",
    ":hover": {
      backgroundColor: tokens.colorNeutralBackground3Hover,
    },
  },
  reportItemActive: {
    backgroundColor: tokens.colorBrandBackground2,
    ":hover": {
      backgroundColor: tokens.colorBrandBackground2Hover,
    },
  },
  reportIcon: {
    fontSize: "20px",
    color: tokens.colorBrandForeground1,
  },
  reportName: {
    flex: 1,
    fontSize: tokens.fontSizeBase300,
    wordBreak: "break-word",
  },
  viewer: {
    flex: 1,
    display: "flex",
    flexDirection: "column",
    position: "relative",
  },
  iframe: {
    flex: 1,
    border: "none",
    backgroundColor: tokens.colorNeutralBackground1,
  },
  emptyState: {
    flex: 1,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    gap: "16px",
    padding: "48px",
    textAlign: "center",
  },
  emptyStateIcon: {
    fontSize: "48px",
    color: tokens.colorNeutralForeground3,
  },
  emptyStateText: {
    fontSize: tokens.fontSizeBase400,
    color: tokens.colorNeutralForeground2,
  },
  loadingContainer: {
    flex: 1,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
});
