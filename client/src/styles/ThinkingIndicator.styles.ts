// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * ThinkingIndicator Styles
 * Fluent UI makeStyles for the ThinkingIndicator component.
 */

import { makeStyles, tokens } from "@fluentui/react-components";

export const useStyles = makeStyles({
  container: {
    padding: `${tokens.spacingVerticalM} 0`,
    maxWidth: "900px",
    margin: "0 auto",
    width: "100%",
  },
  header: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalS,
    cursor: "pointer",
    padding: `4px 12px`,
    borderRadius: tokens.borderRadiusCircular,
    backgroundColor: tokens.colorNeutralBackground3,
    width: "fit-content",
    transition: "all 0.2s ease",
    ":hover": {
      backgroundColor: tokens.colorNeutralBackground3Hover,
    },
  },
  headerIcon: {
    color: tokens.colorBrandForeground1,
    fontSize: "14px",
  },
  headerText: {
    fontSize: tokens.fontSizeBase100,
    color: tokens.colorNeutralForeground2,
    fontWeight: tokens.fontWeightMedium,
    textTransform: "none",
    letterSpacing: "normal",
  },
  stepCount: {
    fontSize: tokens.fontSizeBase100,
    color: tokens.colorNeutralForeground4,
    marginLeft: tokens.spacingHorizontalXS,
    marginRight: tokens.spacingHorizontalS,
  },
  headerSpinner: {
    marginLeft: tokens.spacingHorizontalXS,
  },
  stepsList: {
    marginTop: tokens.spacingVerticalS,
    paddingLeft: "16px",
    borderLeft: `1px solid ${tokens.colorNeutralStroke2}`,
    marginLeft: "20px",
    overflow: "hidden",
    transition: "max-height 0.3s ease-out",
  },
  stepsListCollapsed: {
    maxHeight: 0,
  },
  stepsListExpanded: {
    maxHeight: "500px",
  },
  step: {
    display: "flex",
    alignItems: "flex-start",
    gap: tokens.spacingHorizontalS,
    padding: `${tokens.spacingVerticalXS} 0`,
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground2,
  },
  stepIcon: {
    flexShrink: 0,
    marginTop: "2px",
  },
  stepIconPending: {
    color: tokens.colorNeutralForeground3,
  },
  stepIconInProgress: {
    color: tokens.colorBrandForeground1,
  },
  stepIconComplete: {
    color: tokens.colorPaletteGreenForeground1,
  },
  stepIconError: {
    color: tokens.colorPaletteRedForeground1,
  },
  stepContent: {
    flex: 1,
  },
  stepAction: {
    fontWeight: tokens.fontWeightSemibold,
  },
  stepDetail: {
    color: tokens.colorNeutralForeground3,
    fontSize: tokens.fontSizeBase100,
  },
  stepDuration: {
    color: tokens.colorNeutralForeground3,
    fontSize: tokens.fontSizeBase100,
    marginLeft: tokens.spacingHorizontalS,
  },
  stepNested: {
    marginLeft: tokens.spacingHorizontalL,
    borderLeft: `1px solid ${tokens.colorNeutralStroke2}`,
    paddingLeft: tokens.spacingHorizontalS,
  },
  hidden: {
    display: "none",
  },
});
