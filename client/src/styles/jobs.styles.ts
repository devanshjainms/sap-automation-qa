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
  row: {
    cursor: "pointer",
    ":hover": {
      backgroundColor: tokens.colorNeutralBackground1Hover,
    },
  },
});
