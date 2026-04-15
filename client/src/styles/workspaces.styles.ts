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
    cursor: "pointer",
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
  configTable: {
    marginTop: tokens.spacingVerticalS,
    marginBottom: tokens.spacingVerticalM,
  },
  configLabel: {
    fontWeight: tokens.fontWeightSemibold,
    whiteSpace: "nowrap",
    width: "200px",
  },
  hostsList: {
    display: "flex",
    flexWrap: "wrap",
    gap: tokens.spacingHorizontalXS,
  },
  reportCard: {
    cursor: "pointer",
    marginBottom: tokens.spacingVerticalXS,
    transitionProperty: "background-color",
    transitionDuration: "150ms",
    ":hover": {
      backgroundColor: tokens.colorNeutralBackground1Hover,
    },
  },
  reportRow: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: tokens.spacingHorizontalM,
  },
  reportMeta: {
    display: "flex",
    gap: tokens.spacingHorizontalM,
    flexShrink: 0,
  },
  reportView: {
    display: "flex",
    flexDirection: "column",
    height: "100%",
  },
  reportHeader: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalS,
    marginBottom: tokens.spacingVerticalS,
  },
  reportIframe: {
    flexGrow: 1,
    border: `1px solid ${tokens.colorNeutralStroke1}`,
    borderRadius: tokens.borderRadiusMedium,
    width: "100%",
    minHeight: "500px",
  },
});
