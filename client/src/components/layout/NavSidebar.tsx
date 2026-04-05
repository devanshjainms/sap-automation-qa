// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { useState } from "react";
import { NavLink } from "react-router-dom";
import {
  Text,
  mergeClasses,
} from "@fluentui/react-components";
import {
  DataBarVertical24Regular,
  ClipboardTask24Regular,
  CalendarClock24Regular,
  BuildingMultiple24Regular,
  ChevronDown16Regular,
  ChevronRight16Regular,
} from "@fluentui/react-icons";
import { useApi } from "../../hooks/useApi";
import { listConversations } from "../../lib/api";
import { useStyles } from "../../styles/navSidebar.styles";

const NAV_ITEMS = [
  { to: "/dashboard", icon: <DataBarVertical24Regular />, label: "Dashboard", end: false },
  { to: "/jobs", icon: <ClipboardTask24Regular />, label: "Jobs", end: false },
  { to: "/schedules", icon: <CalendarClock24Regular />, label: "Schedules", end: false },
  { to: "/workspaces", icon: <BuildingMultiple24Regular />, label: "Workspaces", end: false },
] as const;

const INITIAL_VISIBLE = 10;

export function NavSidebar() {
  const { data: conversations } = useApi(listConversations, []);
  const classes = useStyles();
  const [expanded, setExpanded] = useState(true);
  const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE);

  const allChats = conversations ?? [];
  const visibleChats = allChats.slice(0, visibleCount);
  const hasMore = allChats.length > visibleCount;

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

      <div className={classes.historySection}>
        <button
          type="button"
          className={classes.historyToggle}
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? <ChevronDown16Regular /> : <ChevronRight16Regular />}
          <Text size={100} weight="semibold">
            CHATS
          </Text>
        </button>
        {expanded && (
          <div className={classes.historyList}>
            {allChats.length === 0 ? (
              <Text
                size={200}
                className={classes.historyEmpty}
                as="p"
              >
                No conversations yet.
              </Text>
            ) : (
              <>
                {visibleChats.map((c) => (
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
                ))}
                {hasMore && (
                  <button
                    type="button"
                    className={classes.loadMore}
                    onClick={() => setVisibleCount((v) => v + INITIAL_VISIBLE)}
                  >
                    Load more
                  </button>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </nav>
  );
}
