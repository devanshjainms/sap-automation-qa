// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Job Section Component
 * Displays job execution interface in the sidebar.
 */

import React, { useState, useEffect, useCallback } from "react";
import {
  Text,
  Button,
  mergeClasses,
  Spinner,
  Badge,
} from "@fluentui/react-components";
import {
  ChevronDownRegular,
  ChevronRightRegular,
  PlayRegular,
  CheckmarkCircleRegular,
  DismissCircleRegular,
  ClockRegular,
  StopRegular,
  ArrowSyncRegular,
} from "@fluentui/react-icons";
import { useJobSectionStyles as useStyles } from "../../styles";
import { jobsApi } from "../../api";
import { JobListItem, JobStatus } from "../../types";

interface JobSectionProps {
  onJobViewToggle?: () => void;
}

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
): "tint" | "filled" => {
  switch (status) {
    case "running":
    case "pending":
      return "tint";
    default:
      return "filled";
  }
};

const formatRelativeTime = (dateString: string): string => {
  try {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffSecs = Math.floor(diffMs / 1000);
    const diffMins = Math.floor(diffSecs / 60);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffSecs < 60) return "Just now";
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  } catch {
    return dateString;
  }
};

export const JobSection: React.FC<JobSectionProps> = ({ onJobViewToggle }) => {
  const styles = useStyles();
  const [isExpanded, setIsExpanded] = useState(false);
  const [jobs, setJobs] = useState<JobListItem[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchJobs = useCallback(async () => {
    try {
      setLoading(true);
      const response = await jobsApi.list({ limit: 10 });
      setJobs(response.jobs);
    } catch (error) {
      console.error("Failed to load jobs:", error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isExpanded) {
      fetchJobs();
    }
  }, [isExpanded, fetchJobs]);

  const toggleExpanded = () => {
    setIsExpanded(!isExpanded);
    if (onJobViewToggle) {
      onJobViewToggle();
    }
  };

  return (
    <div className={styles.section}>
      {/* Section Header */}
      <div className={styles.sectionHeader} onClick={toggleExpanded}>
        <Button
          icon={isExpanded ? <ChevronDownRegular /> : <ChevronRightRegular />}
          appearance="transparent"
          size="small"
          className={styles.expandButton}
        />
        <Text className={styles.sectionTitle}>Job Execution</Text>
        <div className={styles.sectionActions}>
          {isExpanded && (
            <Button
              icon={<ArrowSyncRegular />}
              appearance="subtle"
              size="small"
              onClick={(e) => {
                e.stopPropagation();
                fetchJobs();
              }}
            />
          )}
        </div>
      </div>

      {/* Section Content */}
      {isExpanded && (
        <div className={styles.sectionContent}>
          {loading ? (
            <div className={styles.loadingContainer}>
              <Spinner size="small" />
            </div>
          ) : jobs.length === 0 ? (
            <div className={styles.emptyState}>
              <Text>No jobs found</Text>
            </div>
          ) : (
            <div className={styles.list}>
              {jobs.map((job) => (
                <div key={job.job_id} className={styles.jobItem}>
                  <div className={styles.jobIcon}>
                    {getStatusIcon(job.status)}
                  </div>
                  <div className={styles.jobContent}>
                    <Text className={styles.jobTitle}>
                      {job.test_id}
                    </Text>
                    <Text className={styles.jobSubtitle}>
                      {job.workspace_id} • {formatRelativeTime(job.created_at)}
                    </Text>
                  </div>
                  <Badge appearance={getStatusBadge(job.status)} size="small" color={
                    job.status === "completed" ? "success" :
                    job.status === "failed" ? "danger" :
                    job.status === "running" ? "brand" :
                    job.status === "cancelled" ? "warning" :
                    "informative"
                  }>
                    {job.status}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
