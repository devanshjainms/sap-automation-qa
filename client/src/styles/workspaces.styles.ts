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
  toolbar: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: tokens.spacingVerticalL,
  },
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(3, 1fr)",
    gap: tokens.spacingHorizontalL,
  },
  card: {
    cursor: "default",
    transitionProperty: "box-shadow",
    transitionDuration: "200ms",
    ":hover": {
      boxShadow: tokens.shadow8,
    },
  },
  cardHeader: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalS,
    marginBottom: tokens.spacingVerticalS,
  },
  path: {
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    display: "block",
    marginBottom: tokens.spacingVerticalS,
  },
});
