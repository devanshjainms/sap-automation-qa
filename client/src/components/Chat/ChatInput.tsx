// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Chat Input Component
 * Input field with workspace chips for sending messages.
 */

import React, { useState, useRef, useEffect, KeyboardEvent } from "react";
import {
  Button,
  Tooltip,
  Dropdown,
  Option,
  Text,
  Spinner,
  mergeClasses,
} from "@fluentui/react-components";
import {
  SendRegular,
  StopRegular,
  FolderRegular,
  DismissRegular,
  AddRegular,
} from "@fluentui/react-icons";
import { useWorkspace } from "../../context";
import { APP_STRINGS, APP_CONFIG } from "../../constants";
import { useChatInputStyles as useStyles } from "../../styles";

interface ChatInputProps {
  onSend: (message: string) => void;
  isLoading: boolean;
  isStreaming: boolean;
  onStop?: () => void;
  disabled?: boolean;
}

export const ChatInput: React.FC<ChatInputProps> = ({
  onSend,
  isLoading,
  isStreaming,
  onStop,
  disabled = false,
}) => {
  const styles = useStyles();
  const [message, setMessage] = useState("");
  const [showWorkspaceDropdown, setShowWorkspaceDropdown] = useState(false);
  const [isFocused, setIsFocused] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const {
    state: workspaceState,
    loadWorkspaces,
    selectWorkspace,
    deselectWorkspace,
  } = useWorkspace();

  useEffect(() => {
    if (workspaceState.workspaces.length === 0 && !workspaceState.isLoading) {
      loadWorkspaces();
    }
  }, [
    workspaceState.workspaces.length,
    workspaceState.isLoading,
    loadWorkspaces,
  ]);

  const availableWorkspaces = workspaceState.workspaces.filter(
    (ws) => !workspaceState.selectedWorkspaceIds.includes(ws.workspace_id),
  );

  const handleWorkspaceSelect = (
    _: unknown,
    data: { optionValue?: string },
  ) => {
    if (data.optionValue) {
      selectWorkspace(data.optionValue);
    }
    setShowWorkspaceDropdown(false);
  };

  const handleRemoveWorkspace = (workspaceId: string) => {
    deselectWorkspace(workspaceId);
  };

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "auto";
      textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
    }
  }, [message]);

  const handleSend = () => {
    const trimmed = message.trim();
    if (trimmed && !isLoading && !disabled) {
      onSend(trimmed);
      setMessage("");
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleStop = () => {
    if (onStop) {
      onStop();
    }
  };

  const canSend = message.trim().length > 0 && !isLoading && !disabled;
  const showStopButton = isStreaming && onStop;
  const hasSelectedWorkspaces = workspaceState.selectedWorkspaceIds.length > 0;

  return (
    <div className={styles.wrapper}>
      <div
        className={mergeClasses(
          styles.inputBox,
          isFocused && styles.inputBoxFocused,
        )}
      >
        {(hasSelectedWorkspaces || showWorkspaceDropdown) && (
          <div className={styles.workspaceChipsRow}>
            {workspaceState.selectedWorkspaceIds.map((wsId) => (
              <div key={wsId} className={styles.workspaceChip}>
                <FolderRegular className={styles.workspaceChipIcon} />
                <Text size={200}>{wsId}</Text>
                <Tooltip content="Remove workspace" relationship="label">
                  <Button
                    className={styles.workspaceChipDismiss}
                    icon={<DismissRegular style={{ fontSize: "10px" }} />}
                    appearance="subtle"
                    size="small"
                    onClick={() => handleRemoveWorkspace(wsId)}
                  />
                </Tooltip>
              </div>
            ))}
            {showWorkspaceDropdown ? (
              <Dropdown
                className={styles.workspaceDropdown}
                placeholder="Select workspace..."
                size="small"
                open={showWorkspaceDropdown}
                onOpenChange={(_, data) => setShowWorkspaceDropdown(data.open)}
                onOptionSelect={handleWorkspaceSelect}
              >
                {availableWorkspaces.map((ws) => (
                  <Option key={ws.workspace_id} value={ws.workspace_id}>
                    {ws.workspace_id}
                  </Option>
                ))}
              </Dropdown>
            ) : availableWorkspaces.length > 0 ? (
              <button
                className={styles.addWorkspaceButton}
                onClick={() => setShowWorkspaceDropdown(true)}
              >
                <AddRegular style={{ fontSize: "12px" }} />
                <span>Add workspace</span>
              </button>
            ) : null}
          </div>
        )}

        <div className={styles.textareaWrapper}>
          <textarea
            ref={textareaRef}
            className={styles.textarea}
            placeholder={APP_STRINGS.CHAT_PLACEHOLDER}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            onFocus={() => setIsFocused(true)}
            onBlur={() => setIsFocused(false)}
            disabled={disabled || isLoading}
            maxLength={APP_CONFIG.MAX_MESSAGE_LENGTH}
            rows={1}
          />
        </div>

        <div className={styles.bottomRow}>
          {!hasSelectedWorkspaces && !showWorkspaceDropdown && (
            <Tooltip content="Add workspace context" relationship="label">
              <Button
                icon={<FolderRegular />}
                appearance="subtle"
                size="small"
                onClick={() => setShowWorkspaceDropdown(true)}
                disabled={
                  workspaceState.isLoading || availableWorkspaces.length === 0
                }
              >
                {workspaceState.isLoading ? (
                  <Spinner size="tiny" />
                ) : (
                  "Workspace"
                )}
              </Button>
            </Tooltip>
          )}

          <div style={{ flex: 1 }} />

          {showStopButton ? (
            <Tooltip
              content={APP_STRINGS.CHAT_STOP_BUTTON}
              relationship="label"
            >
              <Button
                className={styles.sendButton}
                icon={<StopRegular />}
                appearance="primary"
                size="small"
                onClick={handleStop}
              />
            </Tooltip>
          ) : (
            <Tooltip
              content={APP_STRINGS.CHAT_SEND_BUTTON}
              relationship="label"
            >
              <Button
                className={styles.sendButton}
                icon={<SendRegular />}
                appearance="primary"
                size="small"
                onClick={handleSend}
                disabled={!canSend}
              />
            </Tooltip>
          )}
        </div>
      </div>
    </div>
  );
};
