// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * ChatInput Styles
 * Fluent UI makeStyles for the ChatInput component.
 */

import { makeStyles, tokens } from "@fluentui/react-components";

export const useStyles = makeStyles({
  wrapper: {
    display: "flex",
    flexDirection: "column",
    padding: tokens.spacingVerticalM,
    paddingTop: tokens.spacingVerticalS,
    backgroundColor: tokens.colorNeutralBackground1,
  },
  inputBox: {
    display: "flex",
    flexDirection: "column",
    border: `1px solid ${tokens.colorNeutralStroke1}`,
    borderRadius: tokens.borderRadiusLarge,
    backgroundColor: tokens.colorNeutralBackground1,
    overflow: "hidden",
  },
  inputBoxFocused: {
    border: `1px solid ${tokens.colorBrandStroke1}`,
    boxShadow: `0 0 0 1px ${tokens.colorBrandStroke1}`,
  },
  workspaceChipsRow: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    gap: tokens.spacingHorizontalXS,
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalM}`,
    paddingBottom: 0,
  },
  workspaceChip: {
    display: "inline-flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalXS,
    padding: `2px ${tokens.spacingHorizontalS}`,
    backgroundColor: tokens.colorNeutralBackground3,
    borderRadius: tokens.borderRadiusMedium,
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground2,
    border: `1px solid ${tokens.colorNeutralStroke2}`,
  },
  workspaceChipIcon: {
    fontSize: "12px",
    color: tokens.colorBrandForeground1,
  },
  workspaceChipDismiss: {
    padding: "0",
    minWidth: "16px",
    height: "16px",
    borderRadius: "50%",
  },
  addWorkspaceButton: {
    display: "inline-flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalXS,
    padding: `2px ${tokens.spacingHorizontalS}`,
    backgroundColor: "transparent",
    borderRadius: tokens.borderRadiusMedium,
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground3,
    border: `1px dashed ${tokens.colorNeutralStroke2}`,
    cursor: "pointer",
  },
  textareaWrapper: {
    flex: 1,
    display: "flex",
  },
  textarea: {
    flex: 1,
    border: "none",
    outline: "none",
    padding: `${tokens.spacingVerticalM} ${tokens.spacingHorizontalM}`,
    paddingBottom: tokens.spacingVerticalS,
    fontSize: tokens.fontSizeBase300,
    fontFamily: "inherit",
    backgroundColor: "transparent",
    color: tokens.colorNeutralForeground1,
    resize: "none",
    minHeight: "24px",
    maxHeight: "200px",
  },
  bottomRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "flex-end",
    padding: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalS}`,
    paddingTop: 0,
  },
  dropdownContainer: {
    position: "relative",
  },
  workspaceDropdown: {
    minWidth: "240px",
  },
  sendButton: {
    minWidth: "32px",
    height: "32px",
    borderRadius: tokens.borderRadiusMedium,
  },
});
