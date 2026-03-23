// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { makeStyles, tokens } from "@fluentui/react-components";

export const useStyles = makeStyles({
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    paddingLeft: tokens.spacingHorizontalL,
    paddingRight: tokens.spacingHorizontalL,
    height: "48px",
    flexShrink: 0,
    backgroundColor: tokens.colorBrandBackground,
    borderBottom: `1px solid ${tokens.colorBrandBackgroundPressed}`,
  },
  brand: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalM,
  },
  title: {
    color: tokens.colorNeutralForegroundOnBrand,
    fontWeight: tokens.fontWeightSemibold,
    fontSize: tokens.fontSizeBase300,
  },
  actions: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalS,
  },
  headerBtn: {
    color: tokens.colorNeutralForegroundOnBrand,
    borderTopColor: "rgba(255, 255, 255, 0.3)",
    borderRightColor: "rgba(255, 255, 255, 0.3)",
    borderBottomColor: "rgba(255, 255, 255, 0.3)",
    borderLeftColor: "rgba(255, 255, 255, 0.3)",
    ":hover": {
      backgroundColor: "rgba(255, 255, 255, 0.1)",
      borderTopColor: "rgba(255, 255, 255, 0.5)",
      borderRightColor: "rgba(255, 255, 255, 0.5)",
      borderBottomColor: "rgba(255, 255, 255, 0.5)",
      borderLeftColor: "rgba(255, 255, 255, 0.5)",
    },
  },
  themeBtn: {
    color: tokens.colorNeutralForegroundOnBrand,
    ":hover": {
      backgroundColor: "rgba(255, 255, 255, 0.1)",
    },
  },
});
