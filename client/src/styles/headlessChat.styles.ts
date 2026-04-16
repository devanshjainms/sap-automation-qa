// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { makeStyles, shorthands } from "@fluentui/react-components";

export const useStyles = makeStyles({
  container: {
    display: "flex",
    flexDirection: "column",
    height: "100%",
    overflow: "hidden",
  },
  reasoningWrapper: {
    marginTop: "4px",
    marginBottom: "4px",
  },
  reasoningButton: {
    backgroundColor: "transparent",
    ...shorthands.borderStyle("none"),
    paddingTop: "0",
    paddingBottom: "0",
    paddingLeft: "0",
    paddingRight: "0",
    marginTop: "0",
    marginBottom: "0",
    marginLeft: "0",
    marginRight: "0",
    fontFamily: "inherit",
    fontSize: "13px",
    lineHeight: "inherit",
    textAlign: "start" as const,
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    color: "var(--muted-foreground, #888)",
    userSelect: "none",
  },
  reasoningButtonClickable: {
    cursor: "pointer",
  },
  reasoningButtonDefault: {
    cursor: "default",
  },
  reasoningDot: {
    display: "inline-block",
    width: "6px",
    height: "6px",
    borderRadius: "50%",
  },
  reasoningDotActive: {
    backgroundColor: "var(--primary, #0f6cbd)",
    animationName: {
      "0%, 100%": { opacity: 1 },
      "50%": { opacity: 0.4 },
    },
    animationDuration: "1.2s",
    animationIterationCount: "infinite",
  },
  reasoningDotInactive: {
    backgroundColor: "var(--muted-foreground, #888)",
  },
  reasoningChevron: {
    transitionProperty: "transform",
    transitionDuration: "150ms",
  },
  reasoningChevronOpen: {
    transform: "rotate(90deg)",
  },
  reasoningChevronClosed: {
    transform: "rotate(0deg)",
  },
  reasoningContent: {
    marginTop: "4px",
    paddingLeft: "14px",
    fontSize: "12px",
    lineHeight: "1.5",
    color: "var(--muted-foreground, #888)",
    whiteSpace: "pre-wrap",
    overflowWrap: "break-word",
    borderLeft: "2px solid var(--border, #e0e0e0)",
  },
  reasoningStreamDot: {
    display: "inline-block",
    width: "6px",
    height: "6px",
    borderRadius: "50%",
    backgroundColor: "var(--muted-foreground, #888)",
    marginLeft: "4px",
    verticalAlign: "middle",
    animationName: {
      "0%, 100%": { opacity: 1 },
      "50%": { opacity: 0.4 },
    },
    animationDuration: "1.2s",
    animationIterationCount: "infinite",
  },
});
