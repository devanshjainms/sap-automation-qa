// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { Outlet } from "react-router-dom";
import { Header } from "./Header";
import { NavSidebar } from "./NavSidebar";
import { useStyles } from "../../styles/appShell.styles";

export function AppShell() {
  const classes = useStyles();
  return (
    <div className={classes.shell}>
      <Header />
      <div className={classes.body}>
        <NavSidebar />
        <main className={classes.content}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
