// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { makeStyles, tokens } from "@fluentui/react-components";

export const useStyles = makeStyles({
  overlay: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    height: "100vh",
    fontFamily: tokens.fontFamilyBase,
    color: tokens.colorNeutralForeground3,
  },
  retryButton: {
    marginTop: tokens.spacingVerticalM,
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalL}`,
    borderRadius: tokens.borderRadiusMedium,
    border: `1px solid ${tokens.colorNeutralStroke1}`,
    backgroundColor: tokens.colorNeutralBackground1,
    color: tokens.colorNeutralForeground1,
    cursor: "pointer",
    fontSize: tokens.fontSizeBase300,
    ":hover": {
      backgroundColor: tokens.colorNeutralBackground1Hover,
    },
  },
});
