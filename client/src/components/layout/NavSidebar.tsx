// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { NavLink } from "react-router-dom";
import {
  Text,
  Divider,
  mergeClasses,
} from "@fluentui/react-components";
import {
  Chat24Regular,
  DataBarVertical24Regular,
  ClipboardTask24Regular,
  CalendarClock24Regular,
  BuildingMultiple24Regular,
  Wrench24Regular,
  Open16Regular,
} from "@fluentui/react-icons";
import { useApi } from "../../hooks/useApi";
import { listConversations } from "../../lib/api";
import { useStyles } from "../../styles/navSidebar.styles";

const NAV_ITEMS = [
  { to: "/", icon: <Chat24Regular />, label: "New chat", end: true },
  { to: "/dashboard", icon: <DataBarVertical24Regular />, label: "Dashboard", end: false },
  { to: "/jobs", icon: <ClipboardTask24Regular />, label: "Jobs", end: false },
  { to: "/schedules", icon: <CalendarClock24Regular />, label: "Schedules", end: false },
  { to: "/workspaces", icon: <BuildingMultiple24Regular />, label: "Workspaces", end: false },
] as const;

const DEVUI_URL = `${window.location.protocol}//${window.location.hostname}:8080`;

export function NavSidebar() {
  const { data: conversations } = useApi(listConversations, []);
  const classes = useStyles();

  return (
    <nav className={classes.nav}>
      <ul className={classes.list}>
        {NAV_ITEMS.map(({ to, icon, label, end }) => (
          <li key={to}>
            <NavLink
              to={to}
              end={end}
              className={({ isActive }) =>
                mergeClasses(classes.link, isActive && classes.linkActive)
              }
            >
              {icon}
              <span>{label}</span>
            </NavLink>
          </li>
        ))}
      </ul>

      <Divider />

      <div className={classes.historySection}>
        <Text
          size={100}
          weight="semibold"
          className={classes.historyTitle}
          as="p"
        >
          CHATS
        </Text>
        <div className={classes.historyList}>
          {(conversations ?? []).length === 0 ? (
            <Text
              size={200}
              className={classes.historyEmpty}
              as="p"
            >
              No conversations yet.
            </Text>
          ) : (
            (conversations ?? []).map((c) => (
              <NavLink
                key={c.id}
                to={`/chat/${c.id}`}
                className={({ isActive }) =>
                  mergeClasses(
                    classes.historyItem,
                    isActive && classes.historyItemActive,
                  )
                }
              >
                {c.title || `Chat ${c.id.slice(0, 6)}`}
              </NavLink>
            ))
          )}
        </div>
      </div>

      <div className={classes.footer}>
        <a
          href={DEVUI_URL}
          target="_blank"
          rel="noopener noreferrer"
          className={classes.footerLink}
          title="Open Agent DevUI"
        >
          <Wrench24Regular />
          <span>DevUI</span>
          <Open16Regular className={classes.externalIcon} />
        </a>
      </div>
    </nav>
  );
}
