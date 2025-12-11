// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Test Execution Panel Component
 * Displays test execution status and results.
 */

import React, { useEffect, useState, useCallback } from "react";
import {
  Text,
  Spinner,
  Badge,
  Button,
  ProgressBar,
} from "@fluentui/react-components";
import {
  PlayRegular,
  CheckmarkCircleRegular,
  DismissCircleRegular,
  ClockRegular,
  StopRegular,
} from "@fluentui/react-icons";
import { Job, JobStatus } from "../../types";
import { jobsApi } from "../../api";
import { APP_STRINGS, APP_CONFIG } from "../../constants";
import { useTestExecutionPanelStyles as useStyles } from "../../styles";

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
    default:
      return "subtle";
  }
};

export const TestExecutionPanel: React.FC = () => {
  const styles = useStyles();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [isPolling, setIsPolling] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  const fetchJobs = useCallback(async () => {
    try {
      const fetchedJobs = await jobsApi.list();
      setJobs(fetchedJobs);
      setIsLoading(false);

      // Check if any jobs are still running
      const hasRunningJobs = fetchedJobs.some(
        (job) => job.status === "pending" || job.status === "running",
      );
      setIsPolling(hasRunningJobs);
    } catch (error) {
      console.error("Failed to fetch jobs:", error);
      setIsLoading(false);
    }
  }, []);

  // Poll for job status updates
  useEffect(() => {
    fetchJobs();

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

  const completedCount = jobs.filter((j) => j.status === "completed").length;
  const totalCount = jobs.length;
  const progress = totalCount > 0 ? completedCount / totalCount : 0;

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <Text className={styles.title}>{APP_STRINGS.TEST_PANEL_TITLE}</Text>
        <div className={styles.headerActions}>
          {totalCount > 0 && (
            <Badge appearance="filled" color="informative">
              {completedCount}/{totalCount}
            </Badge>
          )}
          <Button
            icon={<PlayRegular />}
            appearance="subtle"
            size="small"
            onClick={fetchJobs}
          >
            Refresh
          </Button>
        </div>
      </div>

      {totalCount > 0 && (
        <div className={styles.progressContainer}>
          <ProgressBar value={progress} />
        </div>
      )}

      <div className={styles.testList}>
        {isLoading ? (
          <div className={styles.emptyState}>
            <Spinner size="small" label="Loading jobs..." />
          </div>
        ) : jobs.length > 0 ? (
          jobs.map((job) => (
            <div key={job.job_id} className={styles.testItem}>
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
                <Text className={styles.testName}>{job.test_id}</Text>
                <Text className={styles.testDescription}>
                  {job.workspace_id}
                </Text>
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
                  onClick={() => handleCancelJob(job.job_id)}
                />
              )}
            </div>
          ))
        ) : (
          <div className={styles.emptyState}>
            <Text>{APP_STRINGS.TEST_PANEL_EMPTY}</Text>
          </div>
        )}
      </div>
    </div>
  );
};
