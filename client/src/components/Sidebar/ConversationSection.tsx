// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Conversation Section Component
 * Displays conversation history with search and collapsible functionality.
 */

import React, { useState, useEffect, useMemo } from "react";
import {
  Text,
  Button,
  Tooltip,
  Spinner,
  Menu,
  MenuTrigger,
  MenuPopover,
  MenuList,
  MenuItem,
  Dialog,
  DialogTrigger,
  DialogSurface,
  DialogTitle,
  DialogBody,
  DialogActions,
  DialogContent,
  Input,
  mergeClasses,
} from "@fluentui/react-components";
import {
  ChatRegular,
  MoreHorizontalRegular,
  DeleteRegular,
  EditRegular,
  ChevronDownRegular,
  ChevronRightRegular,
  SearchRegular,
  DismissRegular,
} from "@fluentui/react-icons";
import { useChat, useApp } from "../../context";
import { APP_STRINGS } from "../../constants";
import { ConversationListItem } from "../../types";
import { useConversationSectionStyles as useStyles } from "../../styles";

const formatRelativeTime = (dateString: string): string => {
  let normalizedDate = dateString;
  if (
    !dateString.endsWith("Z") &&
    !dateString.includes("+") &&
    !dateString.includes("-", 10)
  ) {
    normalizedDate = dateString + "Z";
  }

  const date = new Date(normalizedDate);
  if (isNaN(date.getTime())) {
    return "Unknown";
  }

  const now = new Date();
  const diffMs = now.getTime() - date.getTime();

  if (diffMs < 0) {
    return "Just now";
  }

  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffSecs < 60) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
};

export const ConversationSection: React.FC = () => {
  const styles = useStyles();
  const {
    state,
    loadConversations,
    loadConversation,
    startNewChat,
    deleteConversation,
    renameConversation,
  } = useChat();
  const { navigateToChat } = useApp();

  const [isExpanded, setIsExpanded] = useState(true);
  const [searchExpanded, setSearchExpanded] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [visibleCount, setVisibleCount] = useState(5);
  const [renameDialogOpen, setRenameDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [selectedConversation, setSelectedConversation] =
    useState<ConversationListItem | null>(null);
  const [newTitle, setNewTitle] = useState("");

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  // Filter conversations based on search query
  const filteredConversations = useMemo(() => {
    if (!searchQuery.trim()) {
      return state.conversations;
    }
    const query = searchQuery.toLowerCase();
    return state.conversations.filter((conv) =>
      conv.title.toLowerCase().includes(query),
    );
  }, [state.conversations, searchQuery]);

  // Visible conversations based on limit
  const visibleConversations = useMemo(() => {
    return filteredConversations.slice(0, visibleCount);
  }, [filteredConversations, visibleCount]);

  const hasMore = filteredConversations.length > visibleCount;

  const handleShowMore = () => {
    setVisibleCount((prev) => prev + 10);
  };

  const handleConversationClick = (conversation: ConversationListItem) => {
    loadConversation(conversation.id);
    navigateToChat();
  };

  const handleNewChat = () => {
    startNewChat();
    navigateToChat();
  };

  const openRenameDialog = (conversation: ConversationListItem) => {
    setSelectedConversation(conversation);
    setNewTitle(conversation.title);
    setRenameDialogOpen(true);
  };

  const openDeleteDialog = (conversation: ConversationListItem) => {
    setSelectedConversation(conversation);
    setDeleteDialogOpen(true);
  };

  const handleRename = async () => {
    if (selectedConversation && newTitle.trim()) {
      await renameConversation(selectedConversation.id, newTitle.trim());
      setRenameDialogOpen(false);
      setSelectedConversation(null);
    }
  };

  const handleDelete = async () => {
    if (selectedConversation) {
      await deleteConversation(selectedConversation.id);
      setDeleteDialogOpen(false);
      setSelectedConversation(null);
    }
  };

  return (
    <div className={styles.section}>
      {/* Section Header */}
      <div className={styles.sectionHeader} onClick={() => setIsExpanded(!isExpanded)}>
        <Button
          icon={isExpanded ? <ChevronDownRegular /> : <ChevronRightRegular />}
          appearance="transparent"
          size="small"
          className={styles.expandButton}
        />
        <Text className={styles.sectionTitle}>Conversations</Text>
        <div className={styles.sectionActions}>
          <Tooltip content={searchExpanded ? "Close search" : "Search conversations"} relationship="label">
            <Button
              icon={searchExpanded ? <DismissRegular /> : <SearchRegular />}
              appearance="subtle"
              size="small"
              onClick={(e) => {
                e.stopPropagation();
                setSearchExpanded(!searchExpanded);
                if (searchExpanded) {
                  setSearchQuery("");
                }
              }}
            />
          </Tooltip>
        </div>
      </div>

      {/* Section Content */}
      {isExpanded && (
        <div className={styles.sectionContent}>
          {/* Search Bar */}
          {searchExpanded && (
            <div className={styles.searchContainer}>
              <Input
                placeholder="Search conversations..."
                value={searchQuery}
                onChange={(_, data) => setSearchQuery(data.value)}
                contentBefore={<SearchRegular />}
                className={styles.searchInput}
                size="small"
                autoFocus
              />
            </div>
          )}

          {/* Conversation List */}
          <div className={styles.list}>
            {state.conversationsLoading ? (
              <div className={styles.loadingContainer}>
                <Spinner size="small" />
              </div>
            ) : filteredConversations.length === 0 ? (
              <div className={styles.emptyState}>
                <Text>
                  {searchQuery
                    ? "No conversations found"
                    : APP_STRINGS.SIDEBAR_NO_CONVERSATIONS}
                </Text>
              </div>
            ) : (
              <>
                {visibleConversations.map((conversation) => (
                  <div
                    key={conversation.id}
                    className={mergeClasses(
                      styles.conversationItem,
                      state.conversationId === conversation.id &&
                        styles.conversationItemActive,
                    )}
                    onClick={() => handleConversationClick(conversation)}
                  >
                    <ChatRegular className={styles.conversationIcon} />
                    <div className={styles.conversationContent}>
                      <Text className={styles.conversationTitle}>
                        {conversation.title || "Untitled"}
                      </Text>
                      <Text className={styles.conversationTime}>
                        {formatRelativeTime(conversation.updated_at)}
                      </Text>
                    </div>
                    <Menu>
                      <MenuTrigger disableButtonEnhancement>
                        <Button
                          className={mergeClasses(
                            styles.conversationActions,
                            "conversation-actions",
                          )}
                          icon={<MoreHorizontalRegular />}
                          appearance="subtle"
                          size="small"
                          onClick={(e) => e.stopPropagation()}
                        />
                      </MenuTrigger>
                      <MenuPopover>
                        <MenuList>
                          <MenuItem
                            icon={<EditRegular />}
                            onClick={(e) => {
                              e.stopPropagation();
                              openRenameDialog(conversation);
                            }}
                          >
                            {APP_STRINGS.ACTION_RENAME}
                          </MenuItem>
                          <MenuItem
                            icon={<DeleteRegular />}
                            onClick={(e) => {
                              e.stopPropagation();
                              openDeleteDialog(conversation);
                            }}
                          >
                            {APP_STRINGS.ACTION_DELETE}
                          </MenuItem>
                        </MenuList>
                      </MenuPopover>
                    </Menu>
                  </div>
                ))}
                {hasMore && (
                  <div className={styles.showMoreContainer}>
                    <Button
                      appearance="subtle"
                      size="small"
                      onClick={handleShowMore}
                      className={styles.showMoreButton}
                    >
                      Show more
                    </Button>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {/* Rename Dialog */}
      <Dialog
        open={renameDialogOpen}
        onOpenChange={(_, data) => setRenameDialogOpen(data.open)}
      >
        <DialogSurface>
          <DialogBody>
            <DialogTitle>{APP_STRINGS.SIDEBAR_RENAME_TITLE}</DialogTitle>
            <DialogContent>
              <Input
                value={newTitle}
                onChange={(_, data) => setNewTitle(data.value)}
                style={{ width: "100%" }}
              />
            </DialogContent>
            <DialogActions>
              <DialogTrigger disableButtonEnhancement>
                <Button appearance="secondary">
                  {APP_STRINGS.ACTION_CANCEL}
                </Button>
              </DialogTrigger>
              <Button appearance="primary" onClick={handleRename}>
                {APP_STRINGS.ACTION_SAVE}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      {/* Delete Dialog */}
      <Dialog
        open={deleteDialogOpen}
        onOpenChange={(_, data) => setDeleteDialogOpen(data.open)}
      >
        <DialogSurface>
          <DialogBody>
            <DialogTitle>{APP_STRINGS.ACTION_DELETE}</DialogTitle>
            <DialogContent>
              <Text>{APP_STRINGS.SIDEBAR_DELETE_CONFIRM}</Text>
            </DialogContent>
            <DialogActions>
              <DialogTrigger disableButtonEnhancement>
                <Button appearance="secondary">
                  {APP_STRINGS.ACTION_CANCEL}
                </Button>
              </DialogTrigger>
              <Button appearance="primary" onClick={handleDelete}>
                {APP_STRINGS.ACTION_DELETE}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
};
