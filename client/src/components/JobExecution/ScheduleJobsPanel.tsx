// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Schedule Jobs Panel Component
 * Displays jobs triggered by a specific schedule with expandable details.
 */

import React, { useEffect, useState, useCallback } from "react";
import {
  Text,
  Spinner,
  Badge,
  Button,
} from "@fluentui/react-components";
import {
  CheckmarkCircleRegular,
  DismissCircleRegular,
  ClockRegular,
  StopRegular,
  ArrowSyncRegular,
} from "@fluentui/react-icons";
import { Job, JobStatus } from "../../types";
import { jobsApi } from "../../api";
import { useSchedule } from "../../context";
import { useJobExecutionPanelStyles as useStyles } from "../../styles";

const getStatusIcon = (status: JobStatus) => {
  switch (status) {
    case "running":
      return <Spinner size="tiny" />;
    case "completed":
      return <CheckmarkCircleRegular />;
    case "failed":
      return <DismissCircleRegular />;
    case "pending":
      return <ClockRegular />;
    case "cancelled":
      return <StopRegular />;
    default:
      return <ClockRegular />;
  }
};

const getStatusBadge = (
  status: JobStatus,
):
  | "brand"
  | "danger"
  | "important"
  | "informative"
  | "severe"
  | "subtle"
  | "success"
  | "warning" => {
  switch (status) {
    case "running":
      return "brand";
    case "completed":
      return "success";
    case "failed":
      return "danger";
    case "pending":
      return "informative";
    case "cancelled":
      return "warning";
    default:
      return "subtle";
  }
};

const formatTimestamp = (timestamp: string): string => {
  try {
    const date = new Date(timestamp);
    return date.toLocaleString();
  } catch {
    return timestamp;
  }
};

interface ScheduleJobsPanelProps {
  scheduleId: string;
}

export const ScheduleJobsPanel: React.FC<ScheduleJobsPanelProps> = ({ scheduleId }) => {
  const styles = useStyles();
  const { getScheduleById } = useSchedule();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const schedule = getScheduleById(scheduleId);

  const loadJobs = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      // Fetch all jobs and filter by schedule_id on client side
      // Note: Backend API should ideally support schedule_id filter parameter
      const response = await jobsApi.list({ limit: 1000 });
      const filteredJobs = response.jobs.filter(
        (job) => job.metadata?.triggered_by_schedule_id === scheduleId
      );
      setJobs(filteredJobs);
    } catch (err) {
      console.error("Failed to load schedule jobs:", err);
      setError(err instanceof Error ? err.message : "Failed to load jobs");
    } finally {
      setIsLoading(false);
    }
  }, [scheduleId]);

  useEffect(() => {
    loadJobs();
    
    // Poll for updates every 5 seconds
    const interval = setInterval(loadJobs, 5000);
    return () => clearInterval(interval);
  }, [loadJobs]);

  if (!schedule) {
    return (
      <div className={styles.container}>
        <div className={styles.header}>
          <Text size={500} weight="semibold">
            Schedule Not Found
          </Text>
        </div>
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div className={styles.emptyState}>
            <Text>Schedule with ID {scheduleId} not found.</Text>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <Text size={500} weight="semibold">
            Schedule: {schedule.name}
          </Text>
        </div>
        <div className={styles.headerActions}>
          <Button
            icon={<ArrowSyncRegular />}
            appearance="subtle"
            onClick={loadJobs}
            disabled={isLoading}
          >
            Refresh
          </Button>
        </div>
      </div>

      {/* Schedule Details */}
      <div style={{ padding: "16px", borderBottom: "1px solid var(--colorNeutralStroke1)" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
          <Text size={300}>
            <strong>Cron:</strong> {schedule.cron_expression}
          </Text>
          <Text size={300}>
            <strong>Timezone:</strong> {schedule.timezone}
          </Text>
          {schedule.description && (
            <Text size={300}>
              <strong>Description:</strong> {schedule.description}
            </Text>
          )}
          <Text size={300}>
            <strong>Workspaces:</strong> {schedule.workspace_ids.join(", ")}
          </Text>
          <Text size={300}>
            <strong>Status:</strong>{" "}
            <Badge appearance={schedule.enabled ? "tint" : "outline"} color={schedule.enabled ? "success" : "subtle"}>
              {schedule.enabled ? "Enabled" : "Disabled"}
            </Badge>
          </Text>
          {schedule.next_run_time && schedule.enabled && (
            <Text size={300}>
              <strong>Next Run:</strong> {formatTimestamp(schedule.next_run_time)}
            </Text>
          )}
          <Text size={300}>
            <strong>Total Runs:</strong> {schedule.total_runs}
          </Text>
        </div>
      </div>

      {/* Jobs List */}
      <div style={{ flex: 1, overflowY: "auto", padding: "16px" }}>
        {isLoading && jobs.length === 0 ? (
          <div style={{ display: "flex", justifyContent: "center", padding: "32px" }}>
            <Spinner size="medium" label="Loading schedule jobs..." />
          </div>
        ) : error ? (
          <div style={{ textAlign: "center", padding: "32px" }}>
            <Text>{error}</Text>
          </div>
        ) : jobs.length === 0 ? (
          <div className={styles.emptyState}>
            <Text>No jobs have been run for this schedule yet.</Text>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            {jobs.map((job) => (
              <div
                key={job.job_id}
                style={{
                  border: "1px solid var(--colorNeutralStroke1)",
                  borderRadius: "8px",
                  padding: "16px",
                  backgroundColor: "var(--colorNeutralBackground1)"
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "8px" }}>
                  <div style={{ display: "flex", gap: "12px", alignItems: "center" }}>
                    <div style={{ display: "flex", alignItems: "center" }}>
                      {getStatusIcon(job.status)}
                    </div>
                    <div>
                      <Text weight="semibold" size={400}>
                        Job {job.job_id}
                      </Text>
                      <Text size={200} style={{ display: "block", color: "var(--colorNeutralForeground3)" }}>
                        Workspace: {job.workspace_id}
                      </Text>
                      <Text size={200} style={{ display: "block", color: "var(--colorNeutralForeground3)" }}>
                        Tests: {job.test_ids.join(", ")}
                      </Text>
                    </div>
                  </div>
                  <div>
                    <Badge appearance="tint" color={getStatusBadge(job.status)}>
                      {job.status}
                    </Badge>
                  </div>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "4px", fontSize: "12px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <Text size={200}>Created:</Text>
                    <Text size={200}>{formatTimestamp(job.created_at)}</Text>
                  </div>
                  {job.started_at && (
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <Text size={200}>Started:</Text>
                      <Text size={200}>{formatTimestamp(job.started_at)}</Text>
                    </div>
                  )}
                  {job.completed_at && (
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <Text size={200}>Completed:</Text>
                      <Text size={200}>{formatTimestamp(job.completed_at)}</Text>
                    </div>
                  )}
                  {job.progress_percent > 0 && (
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <Text size={200}>Progress:</Text>
                      <Text size={200}>{job.progress_percent}%</Text>
                    </div>
                  )}
                  {job.current_step && (
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <Text size={200}>Step:</Text>
                      <Text size={200}>
                        {job.current_step} ({job.current_step_index + 1}/{job.total_steps})
                      </Text>
                    </div>
                  )}
                  {job.error && (
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <Text size={200}>Error:</Text>
                      <Text size={200} style={{ color: "var(--colorPaletteRedForeground1)" }}>
                        {job.error}
                      </Text>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
