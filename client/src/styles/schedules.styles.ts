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
  list: {
    display: "flex",
    flexDirection: "column",
    gap: tokens.spacingVerticalM,
  },
  cardHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: tokens.spacingVerticalS,
  },
  cardTitle: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalS,
  },
  cardActions: {
    display: "flex",
    gap: tokens.spacingHorizontalS,
  },
  detailGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(4, 1fr)",
    gap: tokens.spacingHorizontalS,
  },
});
