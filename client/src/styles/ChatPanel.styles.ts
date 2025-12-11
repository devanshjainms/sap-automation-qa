// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * ChatPanel Styles
 * Fluent UI makeStyles for the ChatPanel component.
 */

import { makeStyles, tokens } from "@fluentui/react-components";

export const useStyles = makeStyles({
  container: {
    display: "flex",
    flexDirection: "column",
    height: "100%",
    backgroundColor: tokens.colorNeutralBackground2,
  },
  messagesContainer: {
    flex: 1,
    overflowY: "auto",
    padding: tokens.spacingVerticalL,
  },
  emptyState: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    height: "100%",
    gap: tokens.spacingVerticalL,
    padding: tokens.spacingHorizontalXXL,
    textAlign: "center" as const,
  },
  emptyStateIcon: {
    fontSize: "64px",
    color: tokens.colorBrandForeground1,
  },
  emptyStateTitle: {
    fontSize: tokens.fontSizeBase500,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground1,
  },
  emptyStateSubtitle: {
    color: tokens.colorNeutralForeground2,
    maxWidth: "400px",
  },
  suggestions: {
    display: "flex",
    flexWrap: "wrap",
    gap: tokens.spacingHorizontalS,
    justifyContent: "center",
    marginTop: tokens.spacingVerticalM,
  },
  suggestionButton: {
    maxWidth: "280px",
  },
  loadingIndicator: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalS,
    padding: tokens.spacingVerticalM,
    maxWidth: "900px",
    margin: "0 auto",
    color: tokens.colorNeutralForeground2,
  },
  errorMessage: {
    padding: tokens.spacingVerticalM,
    margin: `${tokens.spacingVerticalM} auto`,
    maxWidth: "900px",
    backgroundColor: tokens.colorPaletteRedBackground2,
    color: tokens.colorPaletteRedForeground2,
    borderRadius: tokens.borderRadiusMedium,
    textAlign: "center" as const,
  },
});
