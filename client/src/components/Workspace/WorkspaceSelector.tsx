// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Workspace Selector Component
 * Dropdown for selecting workspaces.
 */

import React, { useEffect, useState } from "react";
import {
  Dropdown,
  Option,
  Label,
  Button,
  Spinner,
  Text,
  Tooltip,
} from "@fluentui/react-components";
import {
  FolderRegular,
  DismissRegular,
  ArrowSyncRegular,
} from "@fluentui/react-icons";
import { useWorkspace } from "../../context";
import { APP_STRINGS } from "../../constants";
import { useWorkspaceSelectorStyles as useStyles } from "../../styles";

export const WorkspaceSelector: React.FC = () => {
  const styles = useStyles();
  const { state, loadWorkspaces, selectWorkspace, clearWorkspaces } =
    useWorkspace();
  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    if (state.workspaces.length === 0 && !state.isLoading) {
      loadWorkspaces();
    }
  }, [state.workspaces.length, state.isLoading, loadWorkspaces]);

  const handleSelect = (_: unknown, data: { optionValue?: string }) => {
    if (data.optionValue) {
      selectWorkspace(data.optionValue);
    }
    setIsOpen(false);
  };

  const handleClear = () => {
    clearWorkspaces();
  };

  const handleRefresh = () => {
    loadWorkspaces();
  };

  if (state.isLoading) {
    return (
      <div className={styles.container}>
        <FolderRegular className={styles.icon} />
        <Spinner size="tiny" />
        <Text size={200}>{APP_STRINGS.WORKSPACE_SELECTOR_LOADING}</Text>
      </div>
    );
  }

  const hasSelectedWorkspaces = state.selectedWorkspaceIds.length > 0;

  return (
    <div className={styles.container}>
      <FolderRegular className={styles.icon} />
      <Label>{APP_STRINGS.WORKSPACE_SELECTOR_LABEL}</Label>

      {hasSelectedWorkspaces ? (
        <div className={styles.selectedInfo}>
          <Text>{state.selectedWorkspaceIds.join(", ")}</Text>
          <Tooltip content="Clear selection" relationship="label">
            <Button
              icon={<DismissRegular />}
              appearance="subtle"
              size="small"
              onClick={handleClear}
            />
          </Tooltip>
        </div>
      ) : (
        <Dropdown
          className={styles.dropdown}
          placeholder={APP_STRINGS.WORKSPACE_SELECTOR_PLACEHOLDER}
          open={isOpen}
          onOpenChange={(_, data) => setIsOpen(data.open)}
          onOptionSelect={handleSelect}
        >
          {state.workspaces.map((workspace) => (
            <Option key={workspace.workspace_id} value={workspace.workspace_id}>
              {workspace.workspace_id}
            </Option>
          ))}
        </Dropdown>
      )}

      <div className={styles.actions}>
        <Tooltip content="Refresh workspaces" relationship="label">
          <Button
            icon={<ArrowSyncRegular />}
            appearance="subtle"
            size="small"
            onClick={handleRefresh}
          />
        </Tooltip>
      </div>
    </div>
  );
};
