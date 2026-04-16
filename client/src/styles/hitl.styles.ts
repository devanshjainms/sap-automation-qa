// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { makeStyles, tokens } from "@fluentui/react-components";

export const useHitlStyles = makeStyles({
  container: {
    display: "flex",
    flexDirection: "column",
    gap: "8px",
    padding: "12px 16px",
    borderRadius: "8px",
    border: `1px solid ${tokens.colorNeutralStroke1}`,
    backgroundColor: tokens.colorNeutralBackground2,
    margin: "8px 0",
    fontSize: "13px",
  },
  completed: {
    display: "flex",
    flexDirection: "column",
    gap: "8px",
    padding: "12px 16px",
    borderRadius: "8px",
    border: `1px solid ${tokens.colorNeutralStroke1}`,
    backgroundColor: tokens.colorNeutralBackground2,
    margin: "8px 0",
    fontSize: "13px",
    opacity: 0.7,
  },
  buttonRow: {
    display: "flex",
    gap: "8px",
    marginTop: "4px",
  },
  primaryBtn: {
    padding: "6px 16px",
    borderRadius: "6px",
    border: "none",
    backgroundColor: tokens.colorBrandBackground,
    color: tokens.colorNeutralForegroundOnBrand,
    cursor: "pointer",
    fontSize: "13px",
    fontWeight: 500,
    ":hover": {
      backgroundColor: tokens.colorBrandBackgroundHover,
    },
  },
  secondaryBtn: {
    padding: "6px 16px",
    borderRadius: "6px",
    border: `1px solid ${tokens.colorNeutralStroke1}`,
    backgroundColor: "transparent",
    color: tokens.colorNeutralForeground1,
    cursor: "pointer",
    fontSize: "13px",
    fontWeight: 500,
    ":hover": {
      backgroundColor: tokens.colorNeutralBackground1Hover,
    },
  },
  input: {
    padding: "6px 10px",
    borderRadius: "6px",
    border: `1px solid ${tokens.colorNeutralStroke1}`,
    fontSize: "13px",
    backgroundColor: tokens.colorNeutralBackground1,
    color: tokens.colorNeutralForeground1,
    outlineStyle: "none",
  },
  heading: {
    fontWeight: 500,
  },
  subtitle: {
    color: tokens.colorNeutralForeground3,
  },
  completedText: {
    color: tokens.colorNeutralForeground3,
  },
  codeBlock: {
    fontSize: "12px",
    padding: "8px 10px",
    borderRadius: "6px",
    backgroundColor: tokens.colorNeutralBackground3,
    overflowX: "auto",
    maxHeight: "150px",
    margin: 0,
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
  },
  argsList: {
    display: "flex",
    flexDirection: "column",
    gap: "2px",
    padding: "8px 10px",
    borderRadius: "6px",
    backgroundColor: tokens.colorNeutralBackground3,
    fontSize: "12px",
  },
  argRow: {
    display: "flex",
    gap: "6px",
  },
  argKey: {
    color: tokens.colorNeutralForeground3,
    fontWeight: 500,
    flexShrink: 0,
  },
  argValue: {
    color: tokens.colorNeutralForeground1,
    wordBreak: "break-word",
  },
});
