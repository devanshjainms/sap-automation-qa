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
  heading: {
    marginBottom: tokens.spacingVerticalL,
  },
  list: {
    display: "flex",
    flexDirection: "column",
    gap: tokens.spacingVerticalS,
  },
  card: {
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalM}`,
  },
  cardRow: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalM,
  },
  dot: {
    flexShrink: 0,
    width: "10px",
    height: "10px",
    borderRadius: "50%",
  },
  dotHealthy: { backgroundColor: tokens.colorPaletteGreenForeground1 },
  dotUnhealthy: { backgroundColor: tokens.colorPaletteRedForeground1 },
  dotDefault: { backgroundColor: tokens.colorNeutralForeground4 },
  info: {
    display: "flex",
    flexDirection: "column",
    flex: 1,
    minWidth: 0,
  },
  latency: {
    marginLeft: "auto",
    flexShrink: 0,
  },
  errorDetail: {
    marginTop: tokens.spacingVerticalXS,
    padding: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalS}`,
    backgroundColor: tokens.colorPaletteRedBackground1,
    borderRadius: tokens.borderRadiusSmall,
    color: tokens.colorPaletteRedForeground1,
    wordBreak: "break-word",
  },
});
