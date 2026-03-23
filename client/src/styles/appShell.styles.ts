// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { makeStyles, tokens } from "@fluentui/react-components";

export const useStyles = makeStyles({
  shell: {
    display: "flex",
    flexDirection: "column",
    height: "100vh",
    overflow: "hidden",
    backgroundColor: tokens.colorNeutralBackground1,
    color: tokens.colorNeutralForeground1,
    fontFamily: tokens.fontFamilyBase,
  },
  body: {
    display: "flex",
    flex: "1",
    minHeight: 0,
  },
  content: {
    flex: "1",
    overflowY: "auto",
    backgroundColor: tokens.colorNeutralBackground1,
  },
});
