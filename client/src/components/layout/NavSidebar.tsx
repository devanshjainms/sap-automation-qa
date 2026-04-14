// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import {
  Text,
  Button,
  Tooltip,
  Menu,
  MenuTrigger,
  MenuList,
  MenuItem,
  MenuPopover,
  Avatar,
  mergeClasses,
} from "@fluentui/react-components";
import {
  DataBarVertical24Regular,
  ClipboardTask24Regular,
  CalendarClock24Regular,
  BuildingMultiple24Regular,
  ChevronDown16Regular,
  ChevronRight16Regular,
  SignOut20Regular,
  Person20Regular,
} from "@fluentui/react-icons";
import { useApi } from "../../hooks/useApi";
import { listConversations } from "../../lib/api";
import {
  getOptimisticConversations,
  onConversationsChanged,
  removeOptimistic,
} from "../../lib/conversationEvents";
import { useStyles } from "../../styles/navSidebar.styles";
import { useAuth } from "../../providers/AuthProvider";

const NAV_ITEMS = [
  {
    to: "/dashboard",
    icon: <DataBarVertical24Regular />,
    label: "Dashboard",
    end: false,
  },
  { to: "/jobs", icon: <ClipboardTask24Regular />, label: "Jobs", end: false },
  {
    to: "/schedules",
    icon: <CalendarClock24Regular />,
    label: "Schedules",
    end: false,
  },
  {
    to: "/workspaces",
    icon: <BuildingMultiple24Regular />,
    label: "Workspaces",
    end: false,
  },
] as const;

const INITIAL_VISIBLE = 10;

export function NavSidebar() {
  const { data: conversations, refetch } = useApi(listConversations, []);
  const classes = useStyles();
  const [expanded, setExpanded] = useState(true);
  const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE);
  const [, forceUpdate] = useState(0);
  const { isAuthenticated, isLoading, account, loginPopup, logoutPopup } =
    useAuth();

  useEffect(() => {
    return onConversationsChanged(() => {
      forceUpdate((n) => n + 1);
      const timer = setTimeout(refetch, 2000);
      return () => clearTimeout(timer);
    });
  }, [refetch]);

  const serverChats = conversations ?? [];
  const serverIds = new Set(serverChats.map((c) => c.id));
  const pending = getOptimisticConversations().filter((c) => {
    if (serverIds.has(c.id)) {
      removeOptimistic(c.id);
      return false;
    }
    return true;
  });
  const allChats = [...pending, ...serverChats];
  const visibleChats = allChats.slice(0, visibleCount);
  const hasMore = allChats.length > visibleCount;

  const displayName = account?.name ?? account?.username ?? "";
  const initials = displayName
    .split(" ")
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

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
              <Text size={200} className={classes.historyEmpty} as="p">
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

      {/* User account — pinned to bottom */}
      <div className={classes.userSection}>
        {isAuthenticated && account ? (
          <Menu>
            <MenuTrigger disableButtonEnhancement>
              <button type="button" className={classes.userButton}>
                <Avatar
                  name={displayName}
                  initials={initials}
                  size={28}
                  color="brand"
                />
                <span className={classes.userName}>{displayName}</span>
              </button>
            </MenuTrigger>
            <MenuPopover>
              <MenuList>
                <MenuItem disabled>
                  <Text size={200}>
                    {account.username}
                  </Text>
                </MenuItem>
                <MenuItem
                  icon={<SignOut20Regular />}
                  onClick={() => void logoutPopup()}
                >
                  Sign out
                </MenuItem>
              </MenuList>
            </MenuPopover>
          </Menu>
        ) : (
          <Tooltip content="Sign in" relationship="label">
            <Button
              appearance="subtle"
              size="small"
              icon={<Person20Regular />}
              disabled={isLoading}
              onClick={() => void loginPopup()}
            >
              Sign in
            </Button>
          </Tooltip>
        )}
      </div>
    </nav>
  );
}
