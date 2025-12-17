// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Chat Message Component
 * Displays individual chat messages with markdown rendering.
 */

import React, { useState } from "react";
import { Button, Tooltip, mergeClasses } from "@fluentui/react-components";
import {
  PersonRegular,
  BotSparkleRegular,
  CopyRegular,
  CheckmarkRegular,
  ArrowRightRegular,
} from "@fluentui/react-icons";
import ReactMarkdown from "react-markdown";
import { ChatMessage as ChatMessageType } from "../../types";
import { APP_STRINGS } from "../../constants";
import { useChatMessageStyles as useStyles } from "../../styles";

interface ChatMessageProps {
  message: ChatMessageType;
}

export const ChatMessageComponent: React.FC<ChatMessageProps> = ({
  message,
}) => {
  const styles = useStyles();
  const [copied, setCopied] = useState(false);
  const [isHovered, setIsHovered] = useState(false);

  const isUser = message.role === "user";

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      console.error("Failed to copy:", error);
    }
  };

  return (
    <div
      className={styles.messageWrapper}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <div
        className={mergeClasses(
          styles.messageContainer,
          isUser && styles.userMessage,
        )}
      >
        <div
          className={mergeClasses(
            styles.avatar,
            isUser ? styles.userAvatar : styles.assistantAvatar,
          )}
        >
          {isUser ? <PersonRegular /> : <BotSparkleRegular />}
        </div>
        <div className={styles.messageContent}>
          {!isUser && !!message.metadata?.agent_chain && (
            <div className={styles.agentChain}>
              {(message.metadata.agent_chain as string[]).map((agent: string, i: number) => (
                <span key={i} style={{ display: "contents" }}>
                  <span className={styles.agentBadge}>{agent}</span>
                  {i < (message.metadata!.agent_chain as string[]).length - 1 && (
                    <ArrowRightRegular style={{ fontSize: "12px" }} />
                  )}
                </span>
              ))}
            </div>
          )}
          <div
            className={mergeClasses(
              styles.messageBubble,
              isUser ? styles.userBubble : styles.assistantBubble,
              !isUser && styles.markdown,
            )}
          >
            {isUser ? (
              message.content
            ) : (
              <ReactMarkdown>{message.content}</ReactMarkdown>
            )}
          </div>
          {!isUser && (
            <div
              className={mergeClasses(
                styles.actions,
                "message-actions",
                isHovered && styles.actionsVisible,
              )}
            >
              <Tooltip
                content={
                  copied ? APP_STRINGS.ACTION_COPIED : APP_STRINGS.ACTION_COPY
                }
                relationship="label"
              >
                <Button
                  icon={copied ? <CheckmarkRegular /> : <CopyRegular />}
                  appearance="subtle"
                  size="small"
                  onClick={handleCopy}
                />
              </Tooltip>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
