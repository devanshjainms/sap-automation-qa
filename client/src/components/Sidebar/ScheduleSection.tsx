// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Schedule Section Component
 * Displays schedule list with create, update, delete, enable/disable functionality.
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
  Textarea,
  Switch,
  tokens,
  Dropdown,
  Option,
  Field,
} from "@fluentui/react-components";
import {
  AddRegular,
  CalendarRegular,
  MoreHorizontalRegular,
  DeleteRegular,
  EditRegular,
  ChevronDownRegular,
  ChevronRightRegular,
  PlayRegular,
  PauseRegular,
  ClockRegular,
  CheckmarkCircleRegular,
  DismissCircleRegular,
} from "@fluentui/react-icons";
import { useSchedule, useApp, useWorkspace } from "../../context";
import { CreateScheduleRequest, UpdateScheduleRequest, Schedule } from "../../types";
import { useWorkspaceSectionStyles as useStyles } from "../../styles";

export const ScheduleSection: React.FC = () => {
  const styles = useStyles();
  const { state, loadSchedules, createSchedule, updateSchedule, deleteSchedule, toggleSchedule } = useSchedule();
  const { navigateToScheduleJobs } = useApp();
  const { state: workspaceState } = useWorkspace();

  const [isExpanded, setIsExpanded] = useState(false);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [selectedSchedule, setSelectedSchedule] = useState<Schedule | null>(null);
  
  // Form state for create
  const [newScheduleName, setNewScheduleName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [newCronExpression, setNewCronExpression] = useState("0 0 * * *");
  const [newTimezone, setNewTimezone] = useState("UTC");
  const [newIsEnabled, setNewIsEnabled] = useState(true);
  const [newRunOnCreate, setNewRunOnCreate] = useState(false);
  const [newWorkspaceIds, setNewWorkspaceIds] = useState<string[]>([]);
  const [newTestType, setNewTestType] = useState<string>("SAPFunctionalTests");
  const [newSAPTestType, setNewSAPTestType] = useState<string>("DatabaseHighAvailability");
  const [cronValidationError, setCronValidationError] = useState<string | null>(null);
  
  // Form state for edit
  const [editScheduleName, setEditScheduleName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editCronExpression, setEditCronExpression] = useState("");
  const [editTimezone, setEditTimezone] = useState("");
  const [editIsEnabled, setEditIsEnabled] = useState(true);
  const [editWorkspaceIds, setEditWorkspaceIds] = useState<string[]>([]);
  const [editTestType, setEditTestType] = useState<string>("SAPFunctionalTests");
  const [editSAPTestType, setEditSAPTestType] = useState<string>("DatabaseHighAvailability");
  const [editCronValidationError, setEditCronValidationError] = useState<string | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Validate cron expression format
  const validateCronExpression = (cron: string): string | null => {
    if (!cron.trim()) return "Cron expression is required";
    const parts = cron.trim().split(/\s+/);
    if (parts.length !== 5) {
      return "Cron expression must have exactly 5 fields (minute hour day month weekday)";
    }
    const [minute, hour, day, month, weekday] = parts;
    const isValidField = (field: string, min: number, max: number): boolean => {
      if (field === "*") return true;
      if (field.includes(",")) return field.split(",").every(f => isValidField(f, min, max));
      if (field.includes("/")) {
        const [range, step] = field.split("/");
        return isValidField(range === "*" ? "*" : range, min, max) && !isNaN(Number(step));
      }
      if (field.includes("-")) {
        const [start, end] = field.split("-");
        const s = Number(start), e = Number(end);
        return !isNaN(s) && !isNaN(e) && s >= min && e <= max && s <= e;
      }
      const num = Number(field);
      return !isNaN(num) && num >= min && num <= max;
    };
    if (!isValidField(minute, 0, 59)) return "Invalid minute field (0-59)";
    if (!isValidField(hour, 0, 23)) return "Invalid hour field (0-23)";
    if (!isValidField(day, 1, 31)) return "Invalid day field (1-31)";
    if (!isValidField(month, 1, 12)) return "Invalid month field (1-12)";
    if (!isValidField(weekday, 0, 6)) return "Invalid weekday field (0-6, 0=Sunday)";
    return null;
  };

  useEffect(() => {
    if (isExpanded) {
      loadSchedules();
    }
  }, [isExpanded, loadSchedules]);

  const openCreateDialog = () => {
    setNewScheduleName("");
    setNewDescription("");
    setNewCronExpression("0 0 * * *");
    setNewTimezone("UTC");
    setNewIsEnabled(true);
    setNewRunOnCreate(false);
    setNewWorkspaceIds([]);
    setNewTestType("SAPFunctionalTests");
    setNewSAPTestType("DatabaseHighAvailability");
    setCronValidationError(null);
    setError(null);
    setCreateDialogOpen(true);
  };

  const openEditDialog = (schedule: Schedule) => {
    setSelectedSchedule(schedule);
    setEditScheduleName(schedule.name);
    setEditDescription(schedule.description);
    setEditCronExpression(schedule.cron_expression);
    setEditTimezone(schedule.timezone);
    setEditIsEnabled(schedule.enabled);
    setEditWorkspaceIds(schedule.workspace_ids || []);
    // Parse test_ids to extract test types
    const testIds = schedule.test_ids || [];
    const testTypeValue = testIds.find(id => id === "SAPFunctionalTests" || id === "ConfigurationChecks") || "SAPFunctionalTests";
    const sapTestTypeValue = testIds.find(id => id === "DatabaseHighAvailability" || id === "CentralServicesHighAvailability") || "DatabaseHighAvailability";
    setEditTestType(testTypeValue);
    setEditSAPTestType(sapTestTypeValue);
    setEditCronValidationError(null);
    setError(null);
    setEditDialogOpen(true);
  };

  const openDeleteDialog = (schedule: Schedule) => {
    setSelectedSchedule(schedule);
    setError(null);
    setDeleteDialogOpen(true);
  };

  const handleCreate = async () => {
    // Validate cron expression
    const cronError = validateCronExpression(newCronExpression);
    if (cronError) {
      setCronValidationError(cronError);
      return;
    }
    
    // Validate required fields
    if (!newScheduleName.trim()) {
      setError("Schedule name is required");
      return;
    }
    if (newWorkspaceIds.length === 0) {
      setError("At least one workspace must be selected");
      return;
    }
    
    setLoading(true);
    setError(null);
    try {
      // Build test_ids array from test type selections
      const testIdsArray = [newTestType];
      if (newTestType === "SAPFunctionalTests") {
        testIdsArray.push(newSAPTestType);
      }
      
      const request: CreateScheduleRequest = {
        name: newScheduleName.trim(),
        description: newDescription.trim() || undefined,
        workspace_ids: newWorkspaceIds,
        test_ids: testIdsArray,
        cron_expression: newCronExpression.trim(),
        timezone: newTimezone,
        enabled: newIsEnabled,
      };
      await createSchedule(request);
      setCreateDialogOpen(false);
    } catch (error: any) {
      let errorMsg = "Failed to create schedule";
      if (error?.response?.data?.detail) {
        const detail = error.response.data.detail;
        if (typeof detail === "string") {
          errorMsg = detail;
        } else if (Array.isArray(detail)) {
          errorMsg = detail.map((err: any) => err.msg || JSON.stringify(err)).join(", ");
        } else {
          errorMsg = detail.msg || JSON.stringify(detail);
        }
      } else if (error?.message) {
        errorMsg = error.message;
      }
      console.error("Failed to create schedule:", errorMsg);
      setError(errorMsg);
    } finally {
      setLoading(false);
    }
  };

  const handleUpdate = async () => {
    const cronError = validateCronExpression(editCronExpression);
    if (cronError) {
      setEditCronValidationError(cronError);
      return;
    }
    
    if (!selectedSchedule || !editScheduleName.trim()) return;
    
    // Validate required fields
    if (editWorkspaceIds.length === 0) {
      setError("At least one workspace must be selected");
      return;
    }
    
    setLoading(true);
    setError(null);
    try {
      // Build test_ids array from test type selections
      const testIdsArray = [editTestType];
      if (editTestType === "SAPFunctionalTests") {
        testIdsArray.push(editSAPTestType);
      }
      
      const request: UpdateScheduleRequest = {
        name: editScheduleName.trim(),
        description: editDescription.trim() || undefined,
        workspace_ids: editWorkspaceIds,
        test_ids: testIdsArray,
        cron_expression: editCronExpression.trim(),
        timezone: editTimezone,
        enabled: editIsEnabled,
      };
      await updateSchedule(selectedSchedule.id, request);
      setEditDialogOpen(false);
      setSelectedSchedule(null);
    } catch (error: any) {
      let errorMsg = "Failed to update schedule";
      if (error?.response?.data?.detail) {
        const detail = error.response.data.detail;
        if (typeof detail === "string") {
          errorMsg = detail;
        } else if (Array.isArray(detail)) {
          errorMsg = detail.map((err: any) => err.msg || JSON.stringify(err)).join(", ");
        } else {
          errorMsg = detail.msg || JSON.stringify(detail);
        }
      } else if (error?.message) {
        errorMsg = error.message;
      }
      console.error("Failed to update schedule:", errorMsg);
      setError(errorMsg);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedSchedule) return;

    setLoading(true);
    setError(null);
    try {
      await deleteSchedule(selectedSchedule.id);
      setDeleteDialogOpen(false);
      setSelectedSchedule(null);
    } catch (error: any) {
      let errorMsg = "Failed to delete schedule";
      if (error?.response?.data?.detail) {
        const detail = error.response.data.detail;
        if (typeof detail === "string") {
          errorMsg = detail;
        } else if (Array.isArray(detail)) {
          errorMsg = detail.map((err: any) => err.msg || JSON.stringify(err)).join(", ");
        } else {
          errorMsg = detail.msg || JSON.stringify(detail);
        }
      } else if (error?.message) {
        errorMsg = error.message;
      }
      console.error("Failed to delete schedule:", errorMsg);
      setError(errorMsg);
    } finally {
      setLoading(false);
    }
  };

  const handleToggle = async (schedule: Schedule) => {
    try {
      await toggleSchedule(schedule.id);
    } catch (error: any) {
      let errorMsg = "Failed to toggle schedule";
      if (error?.response?.data?.detail) {
        const detail = error.response.data.detail;
        if (typeof detail === "string") {
          errorMsg = detail;
        } else if (Array.isArray(detail)) {
          errorMsg = detail.map((err: any) => err.msg || JSON.stringify(err)).join(", ");
        } else {
          errorMsg = detail.msg || JSON.stringify(detail);
        }
      } else if (error?.message) {
        errorMsg = error.message;
      }
      console.error("Failed to toggle schedule:", errorMsg);
      setError(errorMsg);
    }
  };

  const handleScheduleClick = (schedule: Schedule) => {
    navigateToScheduleJobs(schedule.id);
  };

  const formatNextRun = (nextRunAt?: string): string => {
    if (!nextRunAt) return "Not scheduled";
    const date = new Date(nextRunAt);
    const now = new Date();
    const diffMs = date.getTime() - now.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    
    if (diffMins < 60) {
      return `in ${diffMins}m`;
    } else if (diffMins < 1440) {
      return `in ${Math.floor(diffMins / 60)}h`;
    } else {
      return `in ${Math.floor(diffMins / 1440)}d`;
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
        <Text className={styles.sectionTitle}>Schedules</Text>
        <div className={styles.sectionActions}>
          <Tooltip content="Create schedule" relationship="label">
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
            ) : state.schedules.length === 0 ? (
              <div className={styles.emptyState}>
                <Text>No schedules found</Text>
              </div>
            ) : (
              state.schedules.map((schedule) => (
                <div key={schedule.id} className={styles.workspaceGroup}>
                  <div
                    className={mergeClasses(
                      styles.workspaceItem,
                    )}
                    onClick={() => handleScheduleClick(schedule)}
                  >
                    <CalendarRegular className={styles.workspaceIcon} />
                    <div className={styles.workspaceContent}>
                      <div className={styles.workspaceTitleRow}>
                        <Text className={styles.workspaceTitle}>
                          {schedule.name}
                        </Text>
                        {schedule.enabled ? (
                          <Tooltip content="Enabled" relationship="label">
                            <CheckmarkCircleRegular className={styles.statusIconEnabled} />
                          </Tooltip>
                        ) : (
                          <Tooltip content="Disabled" relationship="label">
                            <DismissCircleRegular className={styles.statusIconDisabled} />
                          </Tooltip>
                        )}
                      </div>
                    </div>
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
                            icon={<EditRegular />}
                            onClick={(e) => {
                              e.stopPropagation();
                              openEditDialog(schedule);
                            }}
                          >
                            Edit
                          </MenuItem>
                          <MenuItem
                            icon={<DeleteRegular />}
                            onClick={(e) => {
                              e.stopPropagation();
                              openDeleteDialog(schedule);
                            }}
                          >
                            Delete
                          </MenuItem>
                        </MenuList>
                      </MenuPopover>
                    </Menu>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* Create Schedule Dialog */}
      <Dialog
        open={createDialogOpen}
        onOpenChange={(_, data) => setCreateDialogOpen(data.open)}
      >
        <DialogSurface>
          <DialogBody>
            <DialogTitle>Create New Schedule</DialogTitle>
            <DialogContent>
              {error && (
                <MessageBar intent="error" style={{ marginBottom: "12px" }}>
                  <MessageBarBody>{error}</MessageBarBody>
                </MessageBar>
              )}
              <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                <Field label="Schedule Name" required>
                  <Input
                    value={newScheduleName}
                    onChange={(_, data) => setNewScheduleName(data.value)}
                    placeholder="e.g., Daily Health Check"
                  />
                </Field>
                
                <Field label="Description">
                  <Textarea
                    value={newDescription}
                    onChange={(_, data) => setNewDescription(data.value)}
                    placeholder="Optional description"
                    rows={2}
                  />
                </Field>
                
                <Field label="Workspaces" required validationMessage={newWorkspaceIds.length === 0 ? "Select at least one workspace" : undefined}>
                  <Dropdown
                    multiselect
                    placeholder="Select workspaces"
                    value={newWorkspaceIds.map(id => {
                      const workspace = workspaceState.workspaces.find(w => w.workspace_id === id);
                      return workspace ? `${workspace.workspace_id}${workspace.sid ? ` (${workspace.sid})` : ''}` : id;
                    }).join(", ")}
                    selectedOptions={newWorkspaceIds}
                    onOptionSelect={(_, data) => {
                      setNewWorkspaceIds(data.selectedOptions);
                    }}
                  >
                    {workspaceState.workspaces.map((workspace) => {
                      const displayText = `${workspace.workspace_id}${workspace.sid ? ` (${workspace.sid})` : ''}`;
                      return (
                        <Option key={workspace.workspace_id} value={workspace.workspace_id} text={displayText}>
                          {displayText}
                        </Option>
                      );
                    })}
                  </Dropdown>
                  <Text size={200} style={{ marginTop: "4px", color: tokens.colorNeutralForeground3 }}>
                    {newWorkspaceIds.length} workspace(s) selected
                  </Text>
                </Field>
                
                <Field label="Test Type" required>
                  <Dropdown
                    placeholder="Select test type"
                    value={newTestType}
                    selectedOptions={[newTestType]}
                    onOptionSelect={(_, data) => {
                      if (data.optionValue) {
                        setNewTestType(data.optionValue);
                      }
                    }}
                  >
                    <Option value="SAPFunctionalTests" text="SAP Functional Tests">
                      SAP Functional Tests
                    </Option>
                    <Option value="ConfigurationChecks" text="Configuration Checks">
                      Configuration Checks
                    </Option>
                  </Dropdown>
                </Field>
                
                {newTestType === "SAPFunctionalTests" && (
                  <Field label="SAP Functional Test Type" required>
                    <Dropdown
                      placeholder="Select SAP test type"
                      value={newSAPTestType}
                      selectedOptions={[newSAPTestType]}
                      onOptionSelect={(_, data) => {
                        if (data.optionValue) {
                          setNewSAPTestType(data.optionValue);
                        }
                      }}
                    >
                      <Option value="DatabaseHighAvailability" text="Database High Availability">
                        Database High Availability
                      </Option>
                      <Option value="CentralServicesHighAvailability" text="Central Services High Availability">
                        Central Services High Availability
                      </Option>
                    </Dropdown>
                  </Field>
                )}
                
                <Field 
                  label="Cron Expression" 
                  required
                  validationMessage={cronValidationError || undefined}
                  validationState={cronValidationError ? "error" : undefined}
                >
                  <Input
                    value={newCronExpression}
                    onChange={(_, data) => {
                      setNewCronExpression(data.value);
                      const error = validateCronExpression(data.value);
                      setCronValidationError(error);
                    }}
                    placeholder="0 0 * * *"
                  />
                  <div style={{ marginTop: "4px" }}>
                    <Text size={200} style={{ color: tokens.colorNeutralForeground3, display: "block" }}>
                      Format: <strong>minute hour day month weekday</strong>
                    </Text>
                    <Text size={200} style={{ color: tokens.colorNeutralForeground3, display: "block", marginTop: "4px" }}>
                      Examples:
                    </Text>
                    <ul style={{ margin: "4px 0", paddingLeft: "20px" }}>
                      <li><Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>0 0 * * * = Daily at midnight</Text></li>
                      <li><Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>0 */6 * * * = Every 6 hours</Text></li>
                      <li><Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>0 9 * * 1 = Every Monday at 9am</Text></li>
                      <li><Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>*/15 * * * * = Every 15 minutes</Text></li>
                      <li><Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>0 0 1 * * = First day of month</Text></li>
                    </ul>
                  </div>
                </Field>
                
                <Field label="Timezone">
                  <Input
                    value={newTimezone}
                    onChange={(_, data) => setNewTimezone(data.value)}
                    placeholder="UTC"
                  />
                </Field>
                
                <Switch
                  checked={newIsEnabled}
                  onChange={(_, data) => setNewIsEnabled(data.checked)}
                  label="Enable immediately"
                />
                
                <Switch
                  checked={newRunOnCreate}
                  onChange={(_, data) => setNewRunOnCreate(data.checked)}
                  label="Run immediately after creation"
                />
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
                disabled={loading || !newScheduleName.trim() || !newCronExpression.trim() || newWorkspaceIds.length === 0 || !!cronValidationError}
              >
                {loading ? <Spinner size="tiny" /> : "Create"}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      {/* Edit Schedule Dialog */}
      <Dialog
        open={editDialogOpen}
        onOpenChange={(_, data) => setEditDialogOpen(data.open)}
      >
        <DialogSurface>
          <DialogBody>
            <DialogTitle>Edit Schedule</DialogTitle>
            <DialogContent>
              {error && (
                <MessageBar intent="error" style={{ marginBottom: "12px" }}>
                  <MessageBarBody>{error}</MessageBarBody>
                </MessageBar>
              )}
              <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                <Field label="Schedule Name" required>
                  <Input
                    value={editScheduleName}
                    onChange={(_, data) => setEditScheduleName(data.value)}
                    placeholder="e.g., Daily Health Check"
                  />
                </Field>
                
                <Field label="Description">
                  <Textarea
                    value={editDescription}
                    onChange={(_, data) => setEditDescription(data.value)}
                    placeholder="Optional description"
                    rows={2}
                  />
                </Field>
                
                <Field label="Workspaces" required validationMessage={editWorkspaceIds.length === 0 ? "Select at least one workspace" : undefined}>
                  <Dropdown
                    multiselect
                    placeholder="Select workspaces"
                    value={editWorkspaceIds.map(id => {
                      const workspace = workspaceState.workspaces.find(w => w.workspace_id === id);
                      return workspace ? `${workspace.workspace_id}${workspace.sid ? ` (${workspace.sid})` : ''}` : id;
                    }).join(", ")}
                    selectedOptions={editWorkspaceIds}
                    onOptionSelect={(_, data) => {
                      setEditWorkspaceIds(data.selectedOptions);
                    }}
                  >
                    {workspaceState.workspaces.map((workspace) => {
                      const displayText = `${workspace.workspace_id}${workspace.sid ? ` (${workspace.sid})` : ''}`;
                      return (
                        <Option 
                          key={workspace.workspace_id} 
                          value={workspace.workspace_id}
                          text={displayText}
                        >
                          {displayText}
                        </Option>
                      );
                    })}
                  </Dropdown>
                  <Text size={200} style={{ marginTop: "4px", color: tokens.colorNeutralForeground3 }}>
                    {editWorkspaceIds.length} workspace(s) selected
                  </Text>
                </Field>
                
                <Field label="Test Type" required>
                  <Dropdown
                    placeholder="Select test type"
                    value={editTestType}
                    selectedOptions={[editTestType]}
                    onOptionSelect={(_, data) => {
                      if (data.optionValue) {
                        setEditTestType(data.optionValue);
                      }
                    }}
                  >
                    <Option value="SAPFunctionalTests" text="SAP Functional Tests">
                      SAP Functional Tests
                    </Option>
                    <Option value="ConfigurationChecks" text="Configuration Checks">
                      Configuration Checks
                    </Option>
                  </Dropdown>
                </Field>
                
                {editTestType === "SAPFunctionalTests" && (
                  <Field label="SAP Functional Test Type" required>
                    <Dropdown
                      placeholder="Select SAP test type"
                      value={editSAPTestType}
                      selectedOptions={[editSAPTestType]}
                      onOptionSelect={(_, data) => {
                        if (data.optionValue) {
                          setEditSAPTestType(data.optionValue);
                        }
                      }}
                    >
                      <Option value="DatabaseHighAvailability" text="Database High Availability">
                        Database High Availability
                      </Option>
                      <Option value="CentralServicesHighAvailability" text="Central Services High Availability">
                        Central Services High Availability
                      </Option>
                    </Dropdown>
                  </Field>
                )}
                
                <Field 
                  label="Cron Expression" 
                  required
                  validationMessage={editCronValidationError || undefined}
                  validationState={editCronValidationError ? "error" : undefined}
                >
                  <Input
                    value={editCronExpression}
                    onChange={(_, data) => {
                      setEditCronExpression(data.value);
                      const error = validateCronExpression(data.value);
                      setEditCronValidationError(error);
                    }}
                    placeholder="0 0 * * *"
                  />
                </Field>
                
                <Field label="Timezone">
                  <Input
                    value={editTimezone}
                    onChange={(_, data) => setEditTimezone(data.value)}
                    placeholder="UTC"
                  />
                </Field>
                
                <Switch
                  checked={editIsEnabled}
                  onChange={(_, data) => setEditIsEnabled(data.checked)}
                  label="Enabled"
                />
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
                onClick={handleUpdate}
                disabled={loading || !editScheduleName.trim() || !editCronExpression.trim() || editWorkspaceIds.length === 0 || !!editCronValidationError}
              >
                {loading ? <Spinner size="tiny" /> : "Save"}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      <Dialog
        open={deleteDialogOpen}
        onOpenChange={(_, data) => setDeleteDialogOpen(data.open)}
      >
        <DialogSurface>
          <DialogBody>
            <DialogTitle>Delete Schedule</DialogTitle>
            <DialogContent>
              {error && (
                <MessageBar intent="error" style={{ marginBottom: "12px" }}>
                  <MessageBarBody>{error}</MessageBarBody>
                </MessageBar>
              )}
              <Text>
                Are you sure you want to delete schedule{" "}
                <strong>{selectedSchedule?.name}</strong>? This action
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
    </div>
  );
};
