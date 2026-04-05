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
  section: {
    marginBottom: tokens.spacingVerticalXL,
  },
  sectionTitle: {
    marginBottom: tokens.spacingVerticalS,
  },
  grid3: {
    display: "grid",
    gridTemplateColumns: "repeat(3, 1fr)",
    gap: tokens.spacingHorizontalM,
  },
  summaryCard: {
    textDecorationLine: "none",
    display: "block",
    padding: tokens.spacingHorizontalM,
    cursor: "pointer",
    transitionProperty: "box-shadow",
    transitionDuration: "150ms",
    ":hover": { boxShadow: tokens.shadow8 },
  },
  summaryValue: {
    fontSize: tokens.fontSizeHero700,
    fontWeight: tokens.fontWeightBold,
    lineHeight: tokens.lineHeightHero700,
  },
  jobList: {
    display: "flex",
    flexDirection: "column",
    gap: "1px",
  },
  jobRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalM}`,
    borderRadius: tokens.borderRadiusMedium,
    textDecorationLine: "none",
    color: tokens.colorNeutralForeground1,
    transitionProperty: "background-color",
    transitionDuration: "150ms",
    ":hover": {
      backgroundColor: tokens.colorNeutralBackground1Hover,
    },
  },
  jobMeta: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalM,
  },
});
