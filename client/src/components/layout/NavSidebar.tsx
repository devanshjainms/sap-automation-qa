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
import { strings } from "../../lib/strings";
import { NAV_ITEMS, INITIAL_VISIBLE_CHATS } from "../../lib/constants";

export function NavSidebar() {
  const { data: conversations, refetch } = useApi(listConversations, []);
  const classes = useStyles();
  const [expanded, setExpanded] = useState(true);
  const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE_CHATS);
  const [, forceUpdate] = useState(0);
  const { isAuthenticated, isLoading, account, loginRedirect, logoutRedirect } =
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
        {NAV_ITEMS.map(({ to, icon, labelKey, end }) => (
          <li key={to}>
            <NavLink
              to={to}
              end={end}
              className={({ isActive }) =>
                mergeClasses(classes.link, isActive && classes.linkActive)
              }
            >
              {icon}
              <span>{strings.nav[labelKey]}</span>
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
            {strings.nav.chats}
          </Text>
        </button>
        {expanded && (
          <div className={classes.historyList}>
            {allChats.length === 0 ? (
              <Text size={200} className={classes.historyEmpty} as="p">
                {strings.nav.noConversations}
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
                    onClick={() =>
                      setVisibleCount((v) => v + INITIAL_VISIBLE_CHATS)
                    }
                  >
                    {strings.nav.loadMore}
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
                  onClick={() => void logoutRedirect()}
                >
                  {strings.auth.signOut}
                </MenuItem>
              </MenuList>
            </MenuPopover>
          </Menu>
        ) : (
          <Tooltip content={strings.auth.signIn} relationship="label">
            <Button
              appearance="subtle"
              size="small"
              icon={<Person20Regular />}
              disabled={isLoading}
              onClick={() => void loginRedirect()}
            >
              {strings.auth.signIn}
            </Button>
          </Tooltip>
        )}
      </div>
    </nav>
  );
}
