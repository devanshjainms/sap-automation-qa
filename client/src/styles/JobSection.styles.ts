// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Job Section Styles
 */

import { makeStyles, tokens, shorthands } from "@fluentui/react-components";

export const useStyles = makeStyles({
  section: {
    display: "flex",
    flexDirection: "column",
    flex: "0 0 auto",
  },
  sectionHeader: {
    display: "flex",
    alignItems: "center",
    ...shorthands.gap(tokens.spacingHorizontalXS),
    ...shorthands.padding(tokens.spacingVerticalXS, tokens.spacingHorizontalM),
    cursor: "pointer",
    userSelect: "none",
    minHeight: "32px",
    ":hover": {
      backgroundColor: tokens.colorSubtleBackgroundHover,
    },
  },
  expandButton: {
    minWidth: "20px",
    ...shorthands.padding("0"),
  },
  sectionTitle: {
    flex: 1,
    fontSize: tokens.fontSizeBase300,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground1,
  },
  sectionContent: {
    ...shorthands.padding(tokens.spacingVerticalM, tokens.spacingHorizontalM),
  },
  jobHint: {
    display: "flex",
    alignItems: "center",
    ...shorthands.gap(tokens.spacingHorizontalS),
    ...shorthands.padding(tokens.spacingVerticalS),
    color: tokens.colorNeutralForeground3,
  },
  jobIcon: {
    fontSize: "16px",
  },
  jobText: {
    fontSize: tokens.fontSizeBase200,
  },
});
