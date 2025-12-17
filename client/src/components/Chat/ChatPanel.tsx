// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Chat Panel Component
 * Main chat interface displaying message history and input.
 */

import React, { useEffect, useRef, useCallback } from "react";
import { Text, Button } from "@fluentui/react-components";
import { BotSparkleRegular } from "@fluentui/react-icons";
import { ChatMessageComponent } from "./ChatMessage";
import { ChatInput } from "./ChatInput";
import { ThinkingIndicator } from "./ThinkingIndicator";
import { ReasoningTraceViewer } from "../ReasoningTrace";
import { useChat, useWorkspace } from "../../context";
import { APP_STRINGS, APP_CONFIG } from "../../constants";
import { useChatPanelStyles as useStyles } from "../../styles";

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
            {state.messages.map((message, index) => {
              const isLastAssistantMessage =
                message.role === "assistant" &&
                index === state.messages.length - 1;
              const showThinkingBeforeThis =
                isLastAssistantMessage && state.thinkingSteps.length > 0;

              return (
                <div key={index}>
                  <>
                    {showThinkingBeforeThis && (
                      <ThinkingIndicator
                        isThinking={false}
                        steps={state.thinkingSteps}
                      />
                    )}
                    <ChatMessageComponent message={message} />
                    {message.role === "assistant" &&
                      message.metadata?.reasoning_trace && (
                        <ReasoningTraceViewer
                          trace={message.metadata.reasoning_trace as any}
                        />
                      )}
                  </>
                </div>
              );
            })}
            {state.isThinking && (
              <ThinkingIndicator
                isThinking={state.isThinking}
                steps={state.thinkingSteps}
              />
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
