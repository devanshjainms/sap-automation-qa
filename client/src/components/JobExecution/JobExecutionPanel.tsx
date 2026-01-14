// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Job Execution Panel Component
 * Displays job execution status and results with workspace filtering and expandable details.
 */

import React, { useEffect, useState, useCallback } from "react";
import {
  Text,
  Spinner,
  Badge,
  Button,
  Dropdown,
  Option,
} from "@fluentui/react-components";
import {
  CheckmarkCircleRegular,
  DismissCircleRegular,
  ClockRegular,
  StopRegular,
  ChevronRightRegular,
  ServerRegular,
  CalendarRegular,
  ArrowSyncRegular,
} from "@fluentui/react-icons";
import { Job, JobListItem, JobStatus } from "../../types";
import { jobsApi } from "../../api";
import { APP_STRINGS, APP_CONFIG } from "../../constants";
import { useJobExecutionPanelStyles as useStyles } from "../../styles";

const ITEMS_PER_PAGE = 20;

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

interface JobRowProps {
  job: JobListItem;
  isExpanded: boolean;
  onToggle: () => void;
  onCancel: (jobId: string) => void;
  styles: ReturnType<typeof useStyles>;
}

const JobRow: React.FC<JobRowProps> = ({ job, isExpanded, onToggle, onCancel, styles }) => {
  const [details, setDetails] = useState<Job | null>(null);
  const [isLoadingDetails, setIsLoadingDetails] = useState(false);

  useEffect(() => {
    if (isExpanded && !details) {
      setIsLoadingDetails(true);
      jobsApi.getById(job.job_id)
        .then(setDetails)
        .catch(console.error)
        .finally(() => setIsLoadingDetails(false));
    }
  }, [isExpanded, job.job_id, details]);

  return (
    <div className={`${styles.testItem} ${isExpanded ? styles.testItemExpanded : ""}`}>
      <div className={styles.testItemHeader} onClick={onToggle}>
        <span className={`${styles.expandIcon} ${isExpanded ? styles.expandIconExpanded : ""}`}>
          <ChevronRightRegular />
        </span>
        <span
          className={`${styles.statusIcon} ${
            job.status === "running"
              ? styles.running
              : job.status === "completed"
                ? styles.completed
                : job.status === "failed"
                  ? styles.failed
                  : styles.pending
          }`}
        >
          {getStatusIcon(job.status)}
        </span>
        <div className={styles.testInfo}>
          <Text className={styles.testName}>
            {job.test_id}
            {job.target_node && (
              <span className={styles.nodeTag}>
                <ServerRegular fontSize={12} /> {job.target_node}
              </span>
            )}
          </Text>
          <div className={styles.metaRow}>
            <span className={styles.metaItem}>
              <CalendarRegular fontSize={12} />
              {formatTimestamp(job.created_at)}
            </span>
            <span className={styles.testDescription}>{job.workspace_id}</span>
          </div>
        </div>
        <Badge
          appearance="filled"
          color={getStatusBadge(job.status)}
          size="small"
        >
          {job.status}
        </Badge>
        {(job.status === "pending" || job.status === "running") && (
          <Button
            icon={<StopRegular />}
            appearance="subtle"
            size="small"
            onClick={(e) => {
              e.stopPropagation();
              onCancel(job.job_id);
            }}
          />
        )}
      </div>

      {isExpanded && (
        <div className={styles.expandedContent}>
          {isLoadingDetails ? (
            <Spinner size="small" label="Loading details..." />
          ) : details ? (
            <>
              <div className={styles.detailSection}>
                <Text className={styles.detailLabel}>Job ID</Text>
                <Text className={styles.detailValue}>{details.job_id}</Text>
              </div>

              <div className={styles.detailSection}>
                <Text className={styles.detailLabel}>Workspace</Text>
                <Text className={styles.detailValue}>{details.workspace_id}</Text>
              </div>

              {details.target_node && (
                <div className={styles.detailSection}>
                  <Text className={styles.detailLabel}>Target Node</Text>
                  <Text className={styles.detailValue}>{details.target_node}</Text>
                </div>
              )}

              {details.target_nodes && details.target_nodes.length > 0 && (
                <div className={styles.detailSection}>
                  <Text className={styles.detailLabel}>Target Nodes</Text>
                  <Text className={styles.detailValue}>{details.target_nodes.join(", ")}</Text>
                </div>
              )}

              {details.started_at && (
                <div className={styles.detailSection}>
                  <Text className={styles.detailLabel}>Started At</Text>
                  <Text className={styles.detailValue}>{formatTimestamp(details.started_at)}</Text>
                </div>
              )}

              {details.completed_at && (
                <div className={styles.detailSection}>
                  <Text className={styles.detailLabel}>Completed At</Text>
                  <Text className={styles.detailValue}>{formatTimestamp(details.completed_at)}</Text>
                </div>
              )}

              {details.error && (
                <div className={styles.detailSection}>
                  <Text className={styles.detailLabel}>Error</Text>
                  <div className={`${styles.outputBox}`} style={{ color: "var(--colorPaletteRedForeground1)" }}>
                    {details.error}
                  </div>
                </div>
              )}

              <div className={styles.detailSection}>
                <Text className={styles.detailLabel}>Standard Output</Text>
                <div className={styles.outputBox}>
                  {details.raw_stdout ? (
                    details.raw_stdout
                  ) : (
                    <span className={styles.outputEmpty}>No output</span>
                  )}
                </div>
              </div>

              <div className={styles.detailSection}>
                <Text className={styles.detailLabel}>Standard Error</Text>
                <div className={styles.outputBox}>
                  {details.raw_stderr ? (
                    details.raw_stderr
                  ) : (
                    <span className={styles.outputEmpty}>No errors</span>
                  )}
                </div>
              </div>
            </>
          ) : (
            <Text className={styles.outputEmpty}>Failed to load details</Text>
          )}n        </div>
      )}
    </div>
  );
};

interface JobExecutionPanelProps {
  workspaceId?: string;
}

export const JobExecutionPanel: React.FC<JobExecutionPanelProps> = ({ workspaceId }) => {
  const styles = useStyles();
  const [jobs, setJobs] = useState<JobListItem[]>([]);
  const [workspaces, setWorkspaces] = useState<string[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState<string>(workspaceId || "");
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);

  // Update selected workspace when prop changes
  useEffect(() => {
    if (workspaceId) {
      setSelectedWorkspace(workspaceId);
    }
  }, [workspaceId]);

  const fetchWorkspaces = useCallback(async () => {
    try {
      const ws = await jobsApi.listWorkspaces();
      setWorkspaces(ws);
    } catch (error) {
      console.error("Failed to fetch workspaces:", error);
    }
  }, []);

  const fetchJobs = useCallback(async () => {
    try {
      const response = await jobsApi.list({
        workspaceId: selectedWorkspace || undefined,
        limit: ITEMS_PER_PAGE,
        offset,
      });
      setJobs(response.jobs);
      setTotal(response.total);
      setIsLoading(false);

      // Check if any jobs are still running
      const hasRunningJobs = response.jobs.some(
        (job) => job.status === "pending" || job.status === "running",
      );
      setIsPolling(hasRunningJobs);
    } catch (error) {
      console.error("Failed to fetch jobs:", error);
      setIsLoading(false);
    }
  }, [selectedWorkspace, offset]);

  // Fetch workspaces on mount
  useEffect(() => {
    fetchWorkspaces();
  }, [fetchWorkspaces]);

  // Fetch jobs when filters change
  useEffect(() => {
    setIsLoading(true);
    fetchJobs();
  }, [fetchJobs]);

  // Poll for job status updates
  useEffect(() => {
    let intervalId: NodeJS.Timeout | null = null;
    if (isPolling) {
      intervalId = setInterval(fetchJobs, APP_CONFIG.JOB_STATUS_POLL_INTERVAL);
    }

    return () => {
      if (intervalId) {
        clearInterval(intervalId);
      }
    };
  }, [isPolling, fetchJobs]);

  const handleCancelJob = async (jobId: string) => {
    try {
      await jobsApi.cancel(jobId);
      fetchJobs();
    } catch (error) {
      console.error("Failed to cancel job:", error);
    }
  };

  const handleWorkspaceChange = (_: unknown, data: { optionValue?: string }) => {
    setSelectedWorkspace(data.optionValue || "");
    setOffset(0);
    setExpandedJobId(null);
  };

  const handleToggleExpand = (jobId: string) => {
    setExpandedJobId(expandedJobId === jobId ? null : jobId);
  };

  const totalPages = Math.ceil(total / ITEMS_PER_PAGE);
  const currentPage = Math.floor(offset / ITEMS_PER_PAGE) + 1;

  const completedCount = jobs.filter((j) => j.status === "completed").length;

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <Text className={styles.title}>{APP_STRINGS.JOB_PANEL_TITLE}</Text>
        <div className={styles.headerActions}>
          {total > 0 && (
            <Badge appearance="filled" color="informative">
              {completedCount}/{jobs.length} on page • {total} total
            </Badge>
          )}
          <Button
            icon={<ArrowSyncRegular />}
            appearance="subtle"
            size="small"
            onClick={fetchJobs}
            title="Refresh"
          />
        </div>
      </div>

      <div className={styles.filterRow}>
        <Text>Workspace:</Text>
        <Dropdown
          className={styles.filterDropdown}
          placeholder="All workspaces"
          value={selectedWorkspace || "All workspaces"}
          selectedOptions={selectedWorkspace ? [selectedWorkspace] : []}
          onOptionSelect={handleWorkspaceChange}
        >
          <Option value="">All workspaces</Option>
          {workspaces.map((ws) => (
            <Option key={ws} value={ws}>
              {ws}
            </Option>
          ))}
        </Dropdown>
      </div>

      <div className={styles.testList}>
        {isLoading ? (
          <div className={styles.emptyState}>
            <Spinner size="small" label="Loading jobs..." />
          </div>
        ) : jobs.length > 0 ? (
          jobs.map((job) => (
            <JobRow
              key={job.job_id}
              job={job}
              isExpanded={expandedJobId === job.job_id}
              onToggle={() => handleToggleExpand(job.job_id)}
              onCancel={handleCancelJob}
              styles={styles}
            />
          ))
        ) : (
          <div className={styles.emptyState}>
            <Text>{APP_STRINGS.JOB_PANEL_EMPTY}</Text>
          </div>
        )}
      </div>

      {totalPages > 1 && (
        <div className={styles.pagination}>
          <Button
            appearance="subtle"
            size="small"
            disabled={currentPage <= 1}
            onClick={() => setOffset(Math.max(0, offset - ITEMS_PER_PAGE))}
          >
            Previous
          </Button>
          <Text>
            Page {currentPage} of {totalPages}
          </Text>
          <Button
            appearance="subtle"
            size="small"
            disabled={currentPage >= totalPages}
            onClick={() => setOffset(offset + ITEMS_PER_PAGE)}
          >
            Next
          </Button>
        </div>
      )}
    </div>
  );
};
