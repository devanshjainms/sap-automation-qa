// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Reports Panel Component
 * Displays and renders HTML test execution reports from quality_assurance directory.
 */

import React, { useState, useEffect } from "react";
import {
  Text,
  Button,
  Spinner,
  tokens,
} from "@fluentui/react-components";
import {
  ArrowSyncRegular,
  DocumentRegular,
} from "@fluentui/react-icons";
import { reportsApi, ReportInfo } from "../../api/reportsApi";
import { useReportsPanelStyles as useStyles } from "../../styles";

interface ReportsPanelProps {
  workspaceId?: string;
}

export const ReportsPanel: React.FC<ReportsPanelProps> = ({ workspaceId }) => {
  const styles = useStyles();
  const [reports, setReports] = useState<ReportInfo[]>([]);
  const [selectedReport, setSelectedReport] = useState<ReportInfo | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [hasQADir, setHasQADir] = useState(true);

  const fetchReports = async () => {
    if (!workspaceId) return;

    setIsLoading(true);
    try {
      const response = await reportsApi.list(workspaceId);
      setReports(response.reports);
      setHasQADir(response.reports.length > 0 || response.quality_assurance_dir !== "");
      
      // Auto-select first report if available
      if (response.reports.length > 0 && !selectedReport) {
        setSelectedReport(response.reports[0]);
      }
    } catch (error) {
      console.error("Failed to fetch reports:", error);
      setReports([]);
      setHasQADir(false);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchReports();
    setSelectedReport(null);
  }, [workspaceId]);

  const getReportUrl = (report: ReportInfo): string => {
    return reportsApi.getReportUrl(workspaceId || "", report.path);
  };

  if (!workspaceId) {
    return (
      <div className={styles.container}>
        <div className={styles.emptyState}>
          <DocumentRegular className={styles.emptyStateIcon} />
          <Text className={styles.emptyStateText}>
            Please select a workspace to view reports
          </Text>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <Text className={styles.title}>
          Test Reports {workspaceId && `- ${workspaceId}`}
        </Text>
        <div className={styles.headerActions}>
          <Button
            icon={<ArrowSyncRegular />}
            appearance="subtle"
            size="small"
            onClick={fetchReports}
            title="Refresh reports"
          />
        </div>
      </div>

      <div className={styles.content}>
        {isLoading ? (
          <div className={styles.loadingContainer}>
            <Spinner size="medium" label="Loading reports..." />
          </div>
        ) : reports.length === 0 ? (
          <div className={styles.emptyState}>
            <DocumentRegular className={styles.emptyStateIcon} />
            <Text className={styles.emptyStateText}>
              {hasQADir 
                ? "No test reports have been generated yet for this workspace."
                : "No quality assurance directory found for this workspace."}
            </Text>
            <Text style={{ fontSize: tokens.fontSizeBase200, color: tokens.colorNeutralForeground3 }}>
              Run tests to generate HTML reports that will appear here.
            </Text>
          </div>
        ) : (
          <>
            <div className={styles.sidebar}>
              <div className={styles.sidebarHeader}>
                <Text weight="semibold">Available Reports ({reports.length})</Text>
              </div>
              <div className={styles.reportList}>
                {reports.map((report) => (
                  <div
                    key={report.path}
                    className={`${styles.reportItem} ${
                      selectedReport?.path === report.path
                        ? styles.reportItemActive
                        : ""
                    }`}
                    onClick={() => setSelectedReport(report)}
                  >
                    <DocumentRegular className={styles.reportIcon} />
                    <Text className={styles.reportName}>{report.name}</Text>
                  </div>
                ))}
              </div>
            </div>

            <div className={styles.viewer}>
              {selectedReport ? (
                <iframe
                  key={selectedReport.path}
                  className={styles.iframe}
                  src={getReportUrl(selectedReport)}
                  title={selectedReport.name}
                  sandbox="allow-scripts allow-same-origin"
                />
              ) : (
                <div className={styles.emptyState}>
                  <Text className={styles.emptyStateText}>
                    Select a report to view
                  </Text>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
};
