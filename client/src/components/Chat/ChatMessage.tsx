// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Chat Message Component
 * Displays individual chat messages with markdown rendering.
 */

import React, { useState } from "react";
import {
  makeStyles,
  tokens,
  Text,
  Button,
  Tooltip,
  mergeClasses,
} from "@fluentui/react-components";
import {
  PersonRegular,
  BotSparkleRegular,
  CopyRegular,
  CheckmarkRegular,
} from "@fluentui/react-icons";
import { ChatMessage as ChatMessageType } from "../../types";
import { APP_STRINGS } from "../../constants";

const useStyles = makeStyles({
  messageContainer: {
    display: "flex",
    gap: tokens.spacingHorizontalM,
    padding: tokens.spacingVerticalM,
    maxWidth: "900px",
    margin: "0 auto",
  },
  userMessage: {
    flexDirection: "row-reverse",
  },
  avatar: {
    width: "32px",
    height: "32px",
    borderRadius: tokens.borderRadiusCircular,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
  },
  userAvatar: {
    backgroundColor: tokens.colorBrandBackground,
    color: tokens.colorNeutralForegroundOnBrand,
  },
  assistantAvatar: {
    backgroundColor: tokens.colorNeutralBackground3,
    color: tokens.colorBrandForeground1,
  },
  messageContent: {
    flex: 1,
    minWidth: 0,
  },
  messageBubble: {
    padding: tokens.spacingVerticalS + " " + tokens.spacingHorizontalM,
    borderRadius: tokens.borderRadiusMedium,
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
    lineHeight: "1.5",
  },
  userBubble: {
    backgroundColor: tokens.colorBrandBackground,
    color: tokens.colorNeutralForegroundOnBrand,
    marginLeft: "auto",
    maxWidth: "80%",
  },
  assistantBubble: {
    backgroundColor: tokens.colorNeutralBackground3,
    color: tokens.colorNeutralForeground1,
  },
  actions: {
    display: "flex",
    gap: tokens.spacingHorizontalXS,
    marginTop: tokens.spacingVerticalXS,
    opacity: 0,
    transition: "opacity 0.2s",
  },
  actionsVisible: {
    opacity: 1,
  },
  messageWrapper: {
    ":hover .message-actions": {
      opacity: 1,
    },
  },
});

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
          <div
            className={mergeClasses(
              styles.messageBubble,
              isUser ? styles.userBubble : styles.assistantBubble,
            )}
          >
            <Text>{message.content}</Text>
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
