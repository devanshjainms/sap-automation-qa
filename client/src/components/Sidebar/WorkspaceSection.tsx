// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Workspace Section Component
 * Displays workspace list with create, update, delete functionality.
 */

import React, { useState, useEffect } from "react";
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
  Label,
  MessageBar,
  MessageBarBody,
  Checkbox,
  tokens,
  Dropdown,
  Option,
  Field,
} from "@fluentui/react-components";
import {
  AddRegular,
  FolderRegular,
  MoreHorizontalRegular,
  DeleteRegular,
  EditRegular,
  ChevronDownRegular,
  ChevronRightRegular,
  DocumentRegular,
  CheckmarkCircleRegular,
  ChatRegular,
  PlayRegular,
  DocumentTableRegular,
} from "@fluentui/react-icons";
import { useWorkspace, useApp } from "../../context";
import { workspacesApi, jobsApi } from "../../api";
import { Workspace } from "../../types";
import { useWorkspaceSectionStyles as useStyles } from "../../styles";

export const WorkspaceSection: React.FC = () => {
  const styles = useStyles();
  const { state, loadWorkspaces, selectWorkspace } = useWorkspace();
  const { navigateToFile, navigateToJobs, navigateToReports } = useApp();

  const [isExpanded, setIsExpanded] = useState(false);
  const [expandedWorkspace, setExpandedWorkspace] = useState<string | null>(null);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [runTestsDialogOpen, setRunTestsDialogOpen] = useState(false);
  const [selectedWorkspace, setSelectedWorkspace] = useState<Workspace | null>(null);
  const [newWorkspaceName, setNewWorkspaceName] = useState("");
  const [useBoilerplate, setUseBoilerplate] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [validWorkspaces, setValidWorkspaces] = useState<Set<string>>(new Set());
  const [selectedTestGroup, setSelectedTestGroup] = useState<string>("CONFIG_CHECKS");
  const [runningTests, setRunningTests] = useState(false);
  const [activeJob, setActiveJob] = useState<any | null>(null);
  const [checkingActiveJob, setCheckingActiveJob] = useState(false);

  useEffect(() => {
    loadWorkspaces();
  }, [loadWorkspaces]);

  // Check which workspaces have both configuration files
  useEffect(() => {
    const checkWorkspaceFiles = async () => {
      const valid = new Set<string>();
      for (const workspace of state.workspaces) {
        try {
          // Try to fetch both files
          await Promise.all([
            workspacesApi.getFileContent(workspace.workspace_id, "sap-parameters.yaml"),
            workspacesApi.getFileContent(workspace.workspace_id, "hosts.yaml"),
          ]);
          valid.add(workspace.workspace_id);
        } catch {
          // Workspace doesn't have both files
        }
      }
      setValidWorkspaces(valid);
    };

    if (state.workspaces.length > 0) {
      checkWorkspaceFiles();
    }
  }, [state.workspaces]);

  const handleWorkspaceClick = (workspace: Workspace) => {
    // Only toggle expansion, don't add to context
    if (expandedWorkspace === workspace.workspace_id) {
      setExpandedWorkspace(null);
    } else {
      setExpandedWorkspace(workspace.workspace_id);
    }
  };

  const handleWorkspaceSelect = (workspace: Workspace) => {
    // Add to context when explicitly selecting
    selectWorkspace(workspace.workspace_id);
  };

  const handleFileClick = (workspaceId: string, fileName: string) => {
    navigateToFile(workspaceId, fileName);
  };

  const openCreateDialog = () => {
    setNewWorkspaceName("");
    setUseBoilerplate(true);
    setError(null);
    setCreateDialogOpen(true);
  };

  const openDeleteDialog = (workspace: Workspace) => {
    setSelectedWorkspace(workspace);
    setError(null);
    setDeleteDialogOpen(true);
  };

  const openRunTestsDialog = async (workspace: Workspace) => {
    setSelectedWorkspace(workspace);
    setSelectedTestGroup("CONFIG_CHECKS");
    setError(null);
    setActiveJob(null);
    setRunTestsDialogOpen(true);
    
    // Check for active jobs
    setCheckingActiveJob(true);
    try {
      const response = await jobsApi.list({ 
        workspaceId: workspace.workspace_id,
        limit: 10 
      });
      
      // Check for running or pending jobs
      const activeJobs = response.jobs?.filter(
        (job: any) => job.status === 'running' || job.status === 'pending'
      );
      
      if (activeJobs && activeJobs.length > 0) {
        setActiveJob(activeJobs[0]);
        console.log('Active job found:', activeJobs[0]);
      } else {
        console.log('No active jobs found for workspace:', workspace.workspace_id);
      }
    } catch (err) {
      console.error('Failed to check active jobs:', err);
    } finally {
      setCheckingActiveJob(false);
    }
  };

  const handleRunTests = async () => {
    if (!selectedWorkspace) return;

    setRunningTests(true);
    setError(null);
    try {
      const response = await workspacesApi.triggerExecution(
        selectedWorkspace.workspace_id,
        {
          test_group: selectedTestGroup as any,
          test_cases: [],
          offline: false,
        }
      );
      
      setRunTestsDialogOpen(false);
      setSelectedWorkspace(null);
      navigateToJobs(selectedWorkspace.workspace_id);
    } catch (error: any) {
      const errorMsg = error?.response?.data?.detail || error?.message || "Failed to start tests";
      console.error("Failed to start tests:", errorMsg);
      setError(errorMsg);
    } finally {
      setRunningTests(false);
    }
  };

  const handleCreate = async () => {
    if (!newWorkspaceName.trim()) return;
    
    setLoading(true);
    setError(null);
    try {
      const workspaceName = newWorkspaceName.trim();
      // Create workspace (with or without boilerplate)
      await workspacesApi.create(workspaceName);
      await loadWorkspaces();
      setCreateDialogOpen(false);
      setNewWorkspaceName("");
      
      // Automatically open sap-parameters.yaml after creation
      if (useBoilerplate) {
        navigateToFile(workspaceName, "sap-parameters.yaml");
      }
    } catch (error: any) {
      const errorMsg = error?.response?.data?.detail || error?.message || "Failed to create workspace";
      console.error("Failed to create workspace:", errorMsg);
      setError(errorMsg);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedWorkspace) return;

    setLoading(true);
    setError(null);
    try {
      await workspacesApi.delete(selectedWorkspace.workspace_id);
      await loadWorkspaces();
      setDeleteDialogOpen(false);
      setSelectedWorkspace(null);
    } catch (error: any) {
      const errorMsg = error?.response?.data?.detail || error?.message || "Failed to delete workspace";
      console.error("Failed to delete workspace:", errorMsg);
      setError(errorMsg);
    } finally {
      setLoading(false);
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
        <Text className={styles.sectionTitle}>Workspaces</Text>
        <div className={styles.sectionActions}>
          <Tooltip content="Create workspace" relationship="label">
            <Button
              icon={<AddRegular />}
              appearance="subtle"
              size="small"
              onClick={(e) => {
                e.stopPropagation();
                openCreateDialog();
              }}
            />
          </Tooltip>
        </div>
      </div>

      {/* Section Content */}
      {isExpanded && (
        <div className={styles.sectionContent}>
          {error && (
            <MessageBar intent="error" className={styles.errorBar}>
              <MessageBarBody>{error}</MessageBarBody>
            </MessageBar>
          )}
          <div className={styles.list}>
            {state.isLoading ? (
              <div className={styles.loadingContainer}>
                <Spinner size="small" />
              </div>
            ) : state.workspaces.length === 0 ? (
              <div className={styles.emptyState}>
                <Text>No workspaces found</Text>
              </div>
            ) : (
              state.workspaces.map((workspace) => (
                <div key={workspace.workspace_id} className={styles.workspaceGroup}>
                  <div
                    className={mergeClasses(
                      styles.workspaceItem,
                      state.selectedWorkspaceIds.includes(workspace.workspace_id) &&
                        styles.workspaceItemActive,
                    )}
                  >
                    <Button
                      icon={
                        expandedWorkspace === workspace.workspace_id ? (
                          <ChevronDownRegular />
                        ) : (
                          <ChevronRightRegular />
                        )
                      }
                      appearance="transparent"
                      size="small"
                      className={styles.expandButton}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleWorkspaceClick(workspace);
                      }}
                    />
                    <div
                      className={styles.workspaceClickArea}
                      onClick={() => handleWorkspaceClick(workspace)}
                    >
                      <FolderRegular className={styles.workspaceIcon} />
                      <div className={styles.workspaceContent}>
                        <Text className={styles.workspaceTitle}>
                          {workspace.workspace_id}
                        </Text>
                        {workspace.sid && (
                          <Text className={styles.workspaceSubtitle}>
                            SID: {workspace.sid}
                          </Text>
                        )}
                      </div>
                      {validWorkspaces.has(workspace.workspace_id) && (
                        <Tooltip content="Valid workspace with configuration files" relationship="label">
                          <CheckmarkCircleRegular className={styles.validIcon} />
                        </Tooltip>
                      )}
                    </div>
                    <Tooltip content="Run tests" relationship="label">
                      <Button
                        icon={<PlayRegular />}
                        appearance="subtle"
                        size="small"
                        className={mergeClasses(styles.contextButton, "context-button")}
                        onClick={(e) => {
                          e.stopPropagation();
                          openRunTestsDialog(workspace);
                        }}
                        disabled={!validWorkspaces.has(workspace.workspace_id)}
                      />
                    </Tooltip>
                    <Menu>
                      <MenuTrigger disableButtonEnhancement>
                        <Button
                          className={styles.workspaceActions}
                          icon={<MoreHorizontalRegular />}
                          appearance="subtle"
                          size="small"
                          onClick={(e) => e.stopPropagation()}
                        />
                      </MenuTrigger>
                      <MenuPopover>
                        <MenuList>
                          <MenuItem
                            icon={<ChatRegular />}
                            onClick={(e) => {
                              e.stopPropagation();
                              handleWorkspaceSelect(workspace);
                            }}
                          >
                            Add to Chat Context
                          </MenuItem>
                          <MenuItem
                            icon={<DeleteRegular />}
                            onClick={(e) => {
                              e.stopPropagation();
                              openDeleteDialog(workspace);
                            }}
                          >
                            Delete
                          </MenuItem>
                        </MenuList>
                      </MenuPopover>
                    </Menu>
                  </div>

                  {/* Workspace Files */}
                  {expandedWorkspace === workspace.workspace_id && (
                    <div className={styles.fileList}>
                      <div
                        className={styles.fileItem}
                        onClick={() =>
                          handleFileClick(workspace.workspace_id, "sap-parameters.yaml")
                        }
                      >
                        <DocumentRegular className={styles.fileIcon} />
                        <Text>sap-parameters.yaml</Text>
                      </div>
                      <div
                        className={styles.fileItem}
                        onClick={() =>
                          handleFileClick(workspace.workspace_id, "hosts.yaml")
                        }
                      >
                        <DocumentRegular className={styles.fileIcon} />
                        <Text>hosts.yaml</Text>
                      </div>
                      <div
                        className={styles.fileItem}
                        onClick={() => navigateToJobs(workspace.workspace_id)}
                      >
                        <PlayRegular className={styles.fileIcon} />
                        <Text>Jobs</Text>
                      </div>
                      <div
                        className={styles.fileItem}
                        onClick={() => navigateToReports(workspace.workspace_id)}
                      >
                        <DocumentTableRegular className={styles.fileIcon} />
                        <Text>Reports</Text>
                      </div>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* Create Workspace Dialog */}
      <Dialog
        open={createDialogOpen}
        onOpenChange={(_, data) => setCreateDialogOpen(data.open)}
      >
        <DialogSurface>
          <DialogBody>
            <DialogTitle>Create New Workspace</DialogTitle>
            <DialogContent>
              {error && (
                <MessageBar intent="error" style={{ marginBottom: "12px" }}>
                  <MessageBarBody>{error}</MessageBarBody>
                </MessageBar>
              )}
              <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                <div>
                  <Label htmlFor="workspace-name">Workspace Name</Label>
                  <Input
                    id="workspace-name"
                    value={newWorkspaceName}
                    onChange={(_, data) => setNewWorkspaceName(data.value)}
                    placeholder="Enter workspace name (e.g., X01, X02)"
                    style={{ width: "100%", marginTop: "4px" }}
                  />
                </div>
                <div>
                  <Checkbox
                    checked={useBoilerplate}
                    onChange={(_, data) => setUseBoilerplate(data.checked as boolean)}
                    label="Populate with sample configuration files"
                  />
                  {useBoilerplate && (
                    <Text 
                      style={{ 
                        fontSize: "12px", 
                        marginTop: "4px",
                        marginLeft: "28px", 
                        display: "block",
                        color: tokens.colorNeutralForeground3 
                      }}
                    >
                      Files will be copied from DEV-WEEU-SAP01-X00 template workspace
                    </Text>
                  )}
                </div>
              </div>
            </DialogContent>
            <DialogActions>
              <DialogTrigger disableButtonEnhancement>
                <Button appearance="secondary" disabled={loading}>
                  Cancel
                </Button>
              </DialogTrigger>
              <Button
                appearance="primary"
                onClick={handleCreate}
                disabled={loading || !newWorkspaceName.trim()}
              >
                {loading ? <Spinner size="tiny" /> : "Create"}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      {/* Delete Workspace Dialog */}
      <Dialog
        open={deleteDialogOpen}
        onOpenChange={(_, data) => setDeleteDialogOpen(data.open)}
      >
        <DialogSurface>
          <DialogBody>
            <DialogTitle>Delete Workspace</DialogTitle>
            <DialogContent>
              {error && (
                <MessageBar intent="error" style={{ marginBottom: "12px" }}>
                  <MessageBarBody>{error}</MessageBarBody>
                </MessageBar>
              )}
              <Text>
                Are you sure you want to delete workspace{" "}
                <strong>{selectedWorkspace?.workspace_id}</strong>? This action
                cannot be undone.
              </Text>
            </DialogContent>
            <DialogActions>
              <DialogTrigger disableButtonEnhancement>
                <Button appearance="secondary" disabled={loading}>
                  Cancel
                </Button>
              </DialogTrigger>
              <Button
                appearance="primary"
                onClick={handleDelete}
                disabled={loading}
              >
                {loading ? <Spinner size="tiny" /> : "Delete"}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      {/* Run Tests Dialog */}
      <Dialog
        open={runTestsDialogOpen}
        onOpenChange={(_, data) => setRunTestsDialogOpen(data.open)}
      >
        <DialogSurface>
          <DialogBody>
            <DialogTitle>Run Tests</DialogTitle>
            <DialogContent>
              {error && (
                <MessageBar intent="error" style={{ marginBottom: "12px" }}>
                  <MessageBarBody>{error}</MessageBarBody>
                </MessageBar>
              )}
              {checkingActiveJob && (
                <MessageBar intent="info" style={{ marginBottom: "12px" }}>
                  <MessageBarBody>
                    <Spinner size="tiny" style={{ marginRight: "8px" }} />
                    Checking for active jobs...
                  </MessageBarBody>
                </MessageBar>
              )}
              {activeJob && (
                <MessageBar intent="warning" style={{ marginBottom: "12px" }}>
                  <MessageBarBody>
                    This workspace has an active job (ID: {activeJob.job_id.substring(0, 8)}...). 
                    Please wait for it to complete or check the Jobs view.
                  </MessageBarBody>
                </MessageBar>
              )}
              <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                <div>
                  <Text weight="semibold">Workspace:</Text>
                  <Text style={{ marginLeft: "8px" }}>
                    {selectedWorkspace?.workspace_id}
                  </Text>
                </div>
                <Field label="Test Group">
                  <Dropdown
                    value={selectedTestGroup}
                    selectedOptions={[selectedTestGroup]}
                    onOptionSelect={(_, data) => setSelectedTestGroup(data.optionValue as string)}
                    style={{ width: "100%" }}
                    disabled={!!activeJob}
                  >
                    <Option value="CONFIG_CHECKS">Configuration Checks</Option>
                    <Option value="HA_DB_HANA">HA Database (HANA)</Option>
                    <Option value="HA_SCS">HA Central Services (SCS)</Option>
                    <Option value="HA_OFFLINE">HA Offline Tests</Option>
                  </Dropdown>
                </Field>
                {!activeJob && (
                  <MessageBar intent="info">
                    <MessageBarBody>
                      Tests will run in the background. You can monitor progress in the Jobs view.
                    </MessageBarBody>
                  </MessageBar>
                )}
              </div>
            </DialogContent>
            <DialogActions>
              <DialogTrigger disableButtonEnhancement>
                <Button appearance="secondary" disabled={runningTests}>
                  Cancel
                </Button>
              </DialogTrigger>
              <Button
                appearance="primary"
                icon={<PlayRegular />}
                onClick={handleRunTests}
                disabled={runningTests || !!activeJob || checkingActiveJob}
              >
                {runningTests ? <Spinner size="tiny" /> : "Run Tests"}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
};
