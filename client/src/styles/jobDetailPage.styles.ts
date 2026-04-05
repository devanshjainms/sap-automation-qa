// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { makeStyles, tokens } from "@fluentui/react-components";

export const useStyles = makeStyles({
  page: {
    maxWidth: "960px",
    width: "100%",
    marginLeft: "auto",
    marginRight: "auto",
    padding: `${tokens.spacingVerticalXL} ${tokens.spacingHorizontalXL}`,
  },
  breadcrumb: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalM,
    marginBottom: tokens.spacingVerticalL,
  },
  meta: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalXL}`,
    padding: tokens.spacingHorizontalL,
    marginBottom: tokens.spacingVerticalL,
  },
  fieldLabel: {
    display: "block",
  },
  actions: {
    display: "flex",
    gap: tokens.spacingHorizontalS,
    marginBottom: tokens.spacingVerticalL,
  },
  logBox: {
    padding: tokens.spacingHorizontalL,
    borderRadius: tokens.borderRadiusMedium,
    backgroundColor: "#1e1e1e",
    color: "#d4d4d4",
    fontFamily: tokens.fontFamilyMonospace,
    fontSize: tokens.fontSizeBase200,
    whiteSpace: "pre-wrap",
    maxHeight: "60vh",
    overflowY: "auto",
  },
});
