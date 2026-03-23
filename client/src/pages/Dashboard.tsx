// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import {
  Card,
  Text,
  Spinner,
  mergeClasses,
} from "@fluentui/react-components";
import { getHealth, listJobs, listSchedules, listWorkspaces } from "../lib/api";
import { useApi } from "../hooks/useApi";
import { StatusBadge } from "../components/shared/StatusBadge";
import type { HealthComponent } from "../lib/types";
import { useStyles } from "../styles/dashboard.styles";

const SERVICE_NAMES = ["core", "mcp", "llm"] as const;

const SERVICE_LABELS: Record<string, string> = {
  core: "Core API",
  mcp: "MCP Server",
  llm: "LLM Connection",
};

export function Dashboard() {
  const health = useApi(getHealth, []);
  const jobs = useApi(listJobs, []);
  const schedules = useApi(listSchedules, []);
  const workspaces = useApi(listWorkspaces, []);
  const classes = useStyles();

  return (
    <div className={classes.page}>
      <Text as="h1" size={600} weight="semibold" className={classes.heading} block>
        Dashboard
      </Text>

      {/* Service Status */}
      <section className={classes.section}>
        <Text as="h2" size={200} weight="semibold" className={classes.sectionTitle} block>
          SERVICE STATUS
        </Text>
        {health.loading ? (
          <Spinner size="small" label="Loading..." />
        ) : (
          <div className={classes.grid3}>
            {health.error
              ? SERVICE_NAMES.map((name) => (
                  <ServiceCard
                    key={name}
                    name={SERVICE_LABELS[name] ?? name}
                    component={{ status: "unhealthy", detail: "Backend unreachable" }}
                    classes={classes}
                  />
                ))
              : SERVICE_NAMES.map((name) => {
                  const comp = health.data?.components?.[name];
                  return (
                    <ServiceCard
                      key={name}
                      name={SERVICE_LABELS[name] ?? name}
                      component={comp ?? { status: "unconfigured", detail: "Not configured" }}
                      classes={classes}
                    />
                  );
                })}
          </div>
        )}
      </section>

      {/* Summary cards */}
      <div className={mergeClasses(classes.grid3, classes.section)}>
        <SummaryCard
          label="Jobs"
          value={jobs.error ? "—" : (jobs.data?.length ?? "—")}
          loading={jobs.loading}
          href="/jobs"
          classes={classes}
        />
        <SummaryCard
          label="Schedules"
          value={schedules.error ? "—" : (schedules.data?.length ?? "—")}
          loading={schedules.loading}
          href="/schedules"
          classes={classes}
        />
        <SummaryCard
          label="Workspaces"
          value={workspaces.error ? "—" : (workspaces.data?.length ?? "—")}
          loading={workspaces.loading}
          href="/workspaces"
          classes={classes}
        />
      </div>

      {/* Recent jobs */}
      <section>
        <Text as="h2" size={200} weight="semibold" className={classes.sectionTitle} block>
          RECENT JOBS
        </Text>
        {jobs.loading ? (
          <Spinner size="small" label="Loading..." />
        ) : jobs.error ? (
          <Text size={300}>Unable to load jobs — backend offline.</Text>
        ) : (
          <Card>
            <div className={classes.jobList}>
              {(jobs.data ?? []).slice(0, 5).map((job) => (
                <a key={job.id} href={`/jobs/${job.id}`} className={classes.jobRow}>
                  <div className={classes.jobMeta}>
                    <Text font="monospace" size={200}>
                      {job.id.slice(0, 8)}
                    </Text>
                    <Text size={300}>{job.playbook}</Text>
                  </div>
                  <StatusBadge status={job.status} />
                </a>
              ))}
              {(jobs.data ?? []).length === 0 && (
                <Text size={300} align="center" block style={{ padding: "1rem" }}>
                  No jobs yet.
                </Text>
              )}
            </div>
          </Card>
        )}
      </section>
    </div>
  );
}

/* ── Sub-components ─────────────────────────────────────────── */

function ServiceCard({
  name,
  component,
  classes,
}: {
  name: string;
  component: HealthComponent;
  classes: ReturnType<typeof useStyles>;
}) {
  const dotClass: Record<string, string> = {
    healthy: classes.dotHealthy,
    unhealthy: classes.dotUnhealthy,
    unconfigured: classes.dotDefault,
  };
  return (
    <Card className={classes.healthCard} size="small">
      <div className={classes.healthHeader}>
        <span className={mergeClasses(classes.dot, dotClass[component.status] ?? classes.dotDefault)} />
        <Text weight="semibold" size={300}>{name}</Text>
      </div>
      <Text size={200}>{component.detail ?? component.status}</Text>
      {component.latency_ms != null && (
        <Text size={200}> · {Math.round(component.latency_ms)} ms</Text>
      )}
    </Card>
  );
}

function SummaryCard({
  label,
  value,
  loading,
  href,
  classes,
}: {
  label: string;
  value: string | number;
  loading: boolean;
  href: string;
  classes: ReturnType<typeof useStyles>;
}) {
  return (
    <Card
      className={classes.summaryCard}
      size="small"
      onClick={() => (window.location.href = href)}
    >
      <Text size={200} weight="semibold" block>
        {label}
      </Text>
      <Text className={classes.summaryValue} block>
        {loading ? "…" : value}
      </Text>
    </Card>
  );
}
