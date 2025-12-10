// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Chat Input Component
 * Input field with workspace chips for sending messages.
 */

import React, { useState, useRef, useEffect, KeyboardEvent } from "react";
import {
  makeStyles,
  tokens,
  Button,
  Tooltip,
  Dropdown,
  Option,
  Text,
  Spinner,
  mergeClasses,
  Badge,
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

const useStyles = makeStyles({
  wrapper: {
    display: "flex",
    flexDirection: "column",
    padding: tokens.spacingVerticalM,
    paddingTop: tokens.spacingVerticalS,
    backgroundColor: tokens.colorNeutralBackground1,
  },
  inputBox: {
    display: "flex",
    flexDirection: "column",
    border: `1px solid ${tokens.colorNeutralStroke1}`,
    borderRadius: tokens.borderRadiusLarge,
    backgroundColor: tokens.colorNeutralBackground1,
    overflow: "hidden",
  },
  inputBoxFocused: {
    border: `1px solid ${tokens.colorBrandStroke1}`,
    boxShadow: `0 0 0 1px ${tokens.colorBrandStroke1}`,
  },
  workspaceChipsRow: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    gap: tokens.spacingHorizontalXS,
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalM}`,
    paddingBottom: 0,
  },
  workspaceChip: {
    display: "inline-flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalXS,
    padding: `2px ${tokens.spacingHorizontalS}`,
    backgroundColor: tokens.colorNeutralBackground3,
    borderRadius: tokens.borderRadiusMedium,
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground2,
    border: `1px solid ${tokens.colorNeutralStroke2}`,
  },
  workspaceChipIcon: {
    fontSize: "12px",
    color: tokens.colorBrandForeground1,
  },
  workspaceChipDismiss: {
    padding: "0",
    minWidth: "16px",
    height: "16px",
    borderRadius: "50%",
  },
  addWorkspaceButton: {
    display: "inline-flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalXS,
    padding: `2px ${tokens.spacingHorizontalS}`,
    backgroundColor: "transparent",
    borderRadius: tokens.borderRadiusMedium,
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground3,
    border: `1px dashed ${tokens.colorNeutralStroke2}`,
    cursor: "pointer",
  },
  textareaWrapper: {
    flex: 1,
    display: "flex",
  },
  textarea: {
    flex: 1,
    border: "none",
    outline: "none",
    padding: `${tokens.spacingVerticalM} ${tokens.spacingHorizontalM}`,
    paddingBottom: tokens.spacingVerticalS,
    fontSize: tokens.fontSizeBase300,
    fontFamily: "inherit",
    backgroundColor: "transparent",
    color: tokens.colorNeutralForeground1,
    resize: "none",
    minHeight: "24px",
    maxHeight: "200px",
  },
  bottomRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "flex-end",
    padding: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalS}`,
    paddingTop: 0,
  },
  dropdownContainer: {
    position: "relative",
  },
  workspaceDropdown: {
    minWidth: "240px",
  },
  sendButton: {
    minWidth: "32px",
    height: "32px",
    borderRadius: tokens.borderRadiusMedium,
  },
});

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
