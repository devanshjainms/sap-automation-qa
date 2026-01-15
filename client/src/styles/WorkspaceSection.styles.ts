// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Workspace Section Styles
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
  errorBar: {
    ...shorthands.margin(tokens.spacingVerticalXS, tokens.spacingHorizontalM),
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
  workspaceGroup: {
    ...shorthands.margin(tokens.spacingVerticalXXS, "0"),
  },
  workspaceItem: {
    display: "flex",
    alignItems: "center",
    ...shorthands.gap(tokens.spacingHorizontalS),
    ...shorthands.padding(tokens.spacingVerticalS, tokens.spacingHorizontalS),
    ...shorthands.borderRadius(tokens.borderRadiusMedium),
    cursor: "pointer",
    position: "relative",
    minHeight: "44px",
    ":hover": {
      backgroundColor: tokens.colorNeutralBackground3Hover,
      "& .context-button": {
        opacity: 1,
      },
    },
  },
  workspaceItemActive: {
    backgroundColor: tokens.colorNeutralBackground3Selected,
  },
  workspaceIcon: {
    fontSize: "16px",
    color: tokens.colorBrandForeground1,
    flexShrink: 0,
  },
  workspaceClickArea: {
    display: "flex",
    alignItems: "center",
    ...shorthands.gap(tokens.spacingHorizontalS),
    flex: 1,
    minWidth: 0,
    cursor: "pointer",
  },
  workspaceContent: {
    flex: 1,
    minWidth: 0,
    display: "flex",
    flexDirection: "column",
    ...shorthands.gap("2px"),
  },
  workspaceTitleRow: {
    display: "flex",
    alignItems: "center",
    ...shorthands.gap(tokens.spacingHorizontalXS),
  },
  workspaceTitle: {
    fontSize: tokens.fontSizeBase200,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground1,
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  workspaceSubtitle: {
    fontSize: tokens.fontSizeBase100,
    color: tokens.colorNeutralForeground3,
  },
  statusIconEnabled: {
    fontSize: "14px",
    color: tokens.colorPaletteGreenForeground1,
  },
  statusIconDisabled: {
    fontSize: "14px",
    color: tokens.colorNeutralForeground3,
  },
  workspaceActions: {
    opacity: 0,
    transition: "opacity 0.2s",
    ":hover": {
      opacity: 1,
    },
  },
  contextButton: {
    opacity: 0,
    transition: "opacity 0.2s",
    flexShrink: 0,
  },
  fileList: {
    display: "flex",
    flexDirection: "column",
    paddingLeft: "48px",
    ...shorthands.gap(tokens.spacingVerticalXXS),
  },
  fileItem: {
    display: "flex",
    alignItems: "center",
    ...shorthands.gap(tokens.spacingHorizontalS),
    ...shorthands.padding(tokens.spacingVerticalXXS, tokens.spacingHorizontalS),
    ...shorthands.borderRadius(tokens.borderRadiusSmall),
    cursor: "pointer",
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground2,
    minHeight: "32px",
    ":hover": {
      backgroundColor: tokens.colorSubtleBackgroundHover,
      color: tokens.colorNeutralForeground1,
    },
  },
  fileIcon: {
    fontSize: "14px",
    color: tokens.colorNeutralForeground3,
  },
  validIcon: {
    fontSize: "16px",
    color: tokens.colorPaletteGreenForeground1,
    flexShrink: 0,
    marginLeft: "auto",
  },
});
