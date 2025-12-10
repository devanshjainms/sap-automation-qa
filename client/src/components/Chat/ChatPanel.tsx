// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Chat Panel Component
 * Main chat interface displaying message history and input.
 */

import React, { useEffect, useRef, useCallback } from "react";
import {
  makeStyles,
  tokens,
  Text,
  Spinner,
  Button,
} from "@fluentui/react-components";
import { BotSparkleRegular } from "@fluentui/react-icons";
import { ChatMessageComponent } from "./ChatMessage";
import { ChatInput } from "./ChatInput";
import { useChat, useWorkspace } from "../../context";
import { APP_STRINGS, APP_CONFIG } from "../../constants";

const useStyles = makeStyles({
  container: {
    display: "flex",
    flexDirection: "column",
    height: "100%",
    backgroundColor: tokens.colorNeutralBackground2,
  },
  messagesContainer: {
    flex: 1,
    overflowY: "auto",
    padding: tokens.spacingVerticalL,
  },
  emptyState: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    height: "100%",
    gap: tokens.spacingVerticalL,
    padding: tokens.spacingHorizontalXXL,
    textAlign: "center",
  },
  emptyStateIcon: {
    fontSize: "64px",
    color: tokens.colorBrandForeground1,
  },
  emptyStateTitle: {
    fontSize: tokens.fontSizeBase500,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground1,
  },
  emptyStateSubtitle: {
    color: tokens.colorNeutralForeground2,
    maxWidth: "400px",
  },
  suggestions: {
    display: "flex",
    flexWrap: "wrap",
    gap: tokens.spacingHorizontalS,
    justifyContent: "center",
    marginTop: tokens.spacingVerticalM,
  },
  suggestionButton: {
    maxWidth: "280px",
  },
  loadingIndicator: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalS,
    padding: tokens.spacingVerticalM,
    maxWidth: "900px",
    margin: "0 auto",
    color: tokens.colorNeutralForeground2,
  },
  errorMessage: {
    padding: tokens.spacingVerticalM,
    margin: tokens.spacingVerticalM + " auto",
    maxWidth: "900px",
    backgroundColor: tokens.colorPaletteRedBackground2,
    color: tokens.colorPaletteRedForeground2,
    borderRadius: tokens.borderRadiusMedium,
    textAlign: "center",
  },
});

const SUGGESTIONS = [
  APP_STRINGS.SUGGESTION_WORKSPACES,
  APP_STRINGS.SUGGESTION_HA_TESTS,
  APP_STRINGS.SUGGESTION_CONFIG_CHECK,
  APP_STRINGS.SUGGESTION_CAPABILITIES,
];

export const ChatPanel: React.FC = () => {
  const styles = useStyles();
  const { state, sendMessage, clearError } = useChat();
  const { state: workspaceState } = useWorkspace();
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    const timer = setTimeout(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, APP_CONFIG.AUTO_SCROLL_DELAY);
    return () => clearTimeout(timer);
  }, [state.messages]);

  // Wrapper to pass workspace IDs with the message
  const handleSendMessage = useCallback(
    (content: string) => {
      sendMessage(content, workspaceState.selectedWorkspaceIds);
    },
    [sendMessage, workspaceState.selectedWorkspaceIds],
  );

  const handleSuggestionClick = (suggestion: string) => {
    handleSendMessage(suggestion);
  };

  const isEmpty = state.messages.length === 0;

  return (
    <div className={styles.container}>
      <div className={styles.messagesContainer}>
        {isEmpty ? (
          <div className={styles.emptyState}>
            <BotSparkleRegular className={styles.emptyStateIcon} />
            <Text className={styles.emptyStateTitle}>
              {APP_STRINGS.CHAT_EMPTY_STATE_TITLE}
            </Text>
            <Text className={styles.emptyStateSubtitle}>
              {APP_STRINGS.CHAT_EMPTY_STATE_SUBTITLE}
            </Text>
            <div className={styles.suggestions}>
              {SUGGESTIONS.map((suggestion, index) => (
                <Button
                  key={index}
                  className={styles.suggestionButton}
                  appearance="outline"
                  onClick={() => handleSuggestionClick(suggestion)}
                >
                  {suggestion}
                </Button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {state.messages.map((message, index) => (
              <ChatMessageComponent key={index} message={message} />
            ))}
            {state.isLoading && (
              <div className={styles.loadingIndicator}>
                <Spinner size="tiny" />
                <Text>{APP_STRINGS.CHAT_THINKING}</Text>
              </div>
            )}
            {state.error && (
              <div className={styles.errorMessage}>
                <Text>{state.error}</Text>
                <Button appearance="subtle" onClick={clearError}>
                  {APP_STRINGS.ACTION_RETRY}
                </Button>
              </div>
            )}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>
      <ChatInput
        onSend={handleSendMessage}
        isLoading={state.isLoading}
        isStreaming={state.isStreaming}
        disabled={false}
      />
    </div>
  );
};
