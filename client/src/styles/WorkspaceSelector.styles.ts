// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * WorkspaceSelector Styles
 * Fluent UI makeStyles for the WorkspaceSelector component.
 */

import { makeStyles, tokens } from "@fluentui/react-components";

export const useStyles = makeStyles({
  container: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalS,
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalM}`,
    backgroundColor: tokens.colorNeutralBackground1,
    borderBottom: `1px solid ${tokens.colorNeutralStroke2}`,
  },
  icon: {
    color: tokens.colorBrandForeground1,
  },
  dropdown: {
    minWidth: "240px",
  },
  actions: {
    display: "flex",
    gap: tokens.spacingHorizontalXS,
  },
  selectedInfo: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalXS,
    padding: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalS}`,
    backgroundColor: tokens.colorBrandBackground2,
    borderRadius: tokens.borderRadiusMedium,
    fontSize: tokens.fontSizeBase200,
  },
});
