// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { useState, useCallback } from "react";
import {
  Button,
  Text,
  Card,
  Badge,
  Spinner,
  DrawerBody,
  DrawerHeader,
  DrawerHeaderTitle,
  OverlayDrawer,
  Table,
  TableBody,
  TableCell,
  TableRow,
  Divider,
  tokens,
} from "@fluentui/react-components";
import {
  ArrowClockwise24Regular,
  BuildingMultiple24Regular,
  Dismiss24Regular,
  DocumentBulletList24Regular,
} from "@fluentui/react-icons";
import {
  listWorkspaces,
  getWorkspaceConfig,
  listWorkspaceReports,
  getWorkspaceReportHtml,
} from "../lib/api";
import type { Workspace, WorkspaceConfig, TestReport } from "../lib/types";
import { useApi } from "../hooks/useApi";
import { useStyles } from "../styles/workspaces.styles";
import { strings } from "../lib/strings";

export function Workspaces() {
  const {
    data: workspaces,
    loading,
    error,
    refetch,
  } = useApi(listWorkspaces, []);
  const classes = useStyles();

  const [selectedWs, setSelectedWs] = useState<Workspace | null>(null);
  const [config, setConfig] = useState<WorkspaceConfig | null>(null);
  const [configLoading, setConfigLoading] = useState(false);
  const [configError, setConfigError] = useState<string | null>(null);
  const [reports, setReports] = useState<TestReport[]>([]);
  const [reportsLoading, setReportsLoading] = useState(false);
  const [reportHtml, setReportHtml] = useState<string | null>(null);
  const [reportName, setReportName] = useState<string | null>(null);
  const [reportLoading, setReportLoading] = useState(false);

  const openDrawer = useCallback((ws: Workspace) => {
    setSelectedWs(ws);
    setConfig(null);
    setConfigError(null);
    setReports([]);
    setReportHtml(null);
    setReportName(null);

    setConfigLoading(true);
    getWorkspaceConfig(ws.id)
      .then(setConfig)
      .catch((e: Error) => setConfigError(e.message))
      .finally(() => setConfigLoading(false));

    setReportsLoading(true);
    listWorkspaceReports(ws.id)
      .then(setReports)
      .finally(() => setReportsLoading(false));
  }, []);

  const closeDrawer = useCallback(() => {
    setSelectedWs(null);
    setReportHtml(null);
    setReportName(null);
  }, []);

  const openReport = useCallback(
    (filename: string) => {
      if (!selectedWs) return;
      setReportLoading(true);
      setReportName(filename);
      getWorkspaceReportHtml(selectedWs.id, filename)
        .then(setReportHtml)
        .finally(() => setReportLoading(false));
    },
    [selectedWs],
  );

  const closeReport = useCallback(() => {
    setReportHtml(null);
    setReportName(null);
  }, []);

  const formatConfigLabel = (key: string): string =>
    key
      .replace(/_/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase());

  return (
    <div className={classes.page}>
      <div className={classes.toolbar}>
        <Text as="h1" size={600} weight="semibold">
          {strings.pages.workspaces.title}
        </Text>
        <Button
          appearance="primary"
          icon={<ArrowClockwise24Regular />}
          onClick={refetch}
        >
          {strings.pages.workspaces.refresh}
        </Button>
      </div>

      {loading && <Spinner size="small" label={strings.shared.loading} />}
      {error && <Text size={300}>{strings.pages.workspaces.loadError}</Text>}

      <div className={classes.grid}>
        {(workspaces ?? []).map((ws) => (
          <Card
            key={ws.id}
            className={classes.card}
            size="small"
            onClick={() => openDrawer(ws)}
          >
            <div className={classes.cardHeader}>
              <BuildingMultiple24Regular />
              <Text weight="semibold" size={300}>
                {ws.name || ws.id}
              </Text>
            </div>
            <Text font="monospace" size={100} className={classes.path}>
              {ws.path}
            </Text>
            <Badge
              appearance="filled"
              color={ws.config_exists ? "success" : "warning"}
              size="small"
            >
              {ws.config_exists
                ? strings.pages.workspaces.configured
                : strings.pages.workspaces.noConfig}
            </Badge>
          </Card>
        ))}
        {(workspaces ?? []).length === 0 && !loading && (
          <Text size={300}>{strings.pages.workspaces.noWorkspaces}</Text>
        )}
      </div>

      <OverlayDrawer
        open={!!selectedWs}
        onOpenChange={(_e, { open }) => {
          if (!open) closeDrawer();
        }}
        position="end"
        size="large"
      >
        <DrawerHeader>
          <DrawerHeaderTitle
            action={
              <Button
                appearance="subtle"
                aria-label="Close"
                icon={<Dismiss24Regular />}
                onClick={closeDrawer}
              />
            }
          >
            {selectedWs?.name || selectedWs?.id}
          </DrawerHeaderTitle>
        </DrawerHeader>
        <DrawerBody>
          {reportHtml !== null ? (
            <div className={classes.reportView}>
              <div className={classes.reportHeader}>
                <Button
                  appearance="subtle"
                  size="small"
                  onClick={closeReport}
                >
                  ← Back to workspace
                </Button>
                <Text size={200} weight="semibold">
                  {reportName}
                </Text>
              </div>
              {reportLoading ? (
                <Spinner size="small" label="Loading report..." />
              ) : (
                <iframe
                  srcDoc={reportHtml}
                  sandbox=""
                  title={reportName ?? "Test Report"}
                  className={classes.reportIframe}
                />
              )}
            </div>
          ) : (
            <>
              {/* Configuration Section */}
              <Text size={400} weight="semibold">
                Configuration
              </Text>
              <Divider style={{ margin: `${tokens.spacingVerticalS} 0` }} />

              {configLoading && (
                <Spinner size="tiny" label="Loading config..." />
              )}
              {configError && (
                <Text
                  size={200}
                  style={{ color: tokens.colorPaletteRedForeground1 }}
                >
                  {configError}
                </Text>
              )}
              {config && (
                <Table size="small" className={classes.configTable}>
                  <TableBody>
                    {Object.entries(config)
                      .filter(([key]) => key !== "hosts")
                      .map(([key, value]) => (
                        <TableRow key={key}>
                          <TableCell className={classes.configLabel}>
                            {formatConfigLabel(key)}
                          </TableCell>
                          <TableCell>
                            {typeof value === "boolean" ? (
                              <Badge
                                appearance="filled"
                                color={value ? "success" : "danger"}
                                size="small"
                              >
                                {value ? "Yes" : "No"}
                              </Badge>
                            ) : (
                              <Text font="monospace" size={200}>
                                {String(value) || "—"}
                              </Text>
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    {config.hosts.length > 0 && (
                      <TableRow>
                        <TableCell className={classes.configLabel}>
                          Hosts
                        </TableCell>
                        <TableCell>
                          <div className={classes.hostsList}>
                            {config.hosts.map((h) => (
                              <Badge
                                key={h}
                                appearance="outline"
                                size="small"
                              >
                                {h}
                              </Badge>
                            ))}
                          </div>
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              )}

              {/* Reports Section */}
              <div style={{ marginTop: tokens.spacingVerticalL }}>
                <Text size={400} weight="semibold">
                  <DocumentBulletList24Regular
                    style={{ verticalAlign: "middle", marginRight: "4px" }}
                  />
                  Recent Test Reports
                </Text>
                <Divider
                  style={{ margin: `${tokens.spacingVerticalS} 0` }}
                />

                {reportsLoading && (
                  <Spinner size="tiny" label="Loading reports..." />
                )}
                {!reportsLoading && reports.length === 0 && (
                  <Text size={200}>
                    No test reports found in this workspace.
                  </Text>
                )}
                {reports.map((r) => (
                  <Card
                    key={r.filename}
                    size="small"
                    className={classes.reportCard}
                    onClick={() => openReport(r.filename)}
                  >
                    <div className={classes.reportRow}>
                      <Text size={200} weight="semibold" truncate>
                        {r.filename}
                      </Text>
                      <div className={classes.reportMeta}>
                        <Text size={100}>
                          {new Date(r.modified_at).toLocaleString()}
                        </Text>
                        <Text size={100}>
                          {(r.size_bytes / 1024).toFixed(1)} KB
                        </Text>
                      </div>
                    </div>
                  </Card>
                ))}
              </div>
            </>
          )}
        </DrawerBody>
      </OverlayDrawer>
    </div>
  );
}
