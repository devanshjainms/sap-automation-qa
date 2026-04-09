// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { Card, Text, Spinner, mergeClasses } from "@fluentui/react-components";
import { listJobs, listSchedules, listWorkspaces } from "../lib/api";
import { useApi } from "../hooks/useApi";
import { StatusBadge } from "../components/shared/StatusBadge";
import { useStyles } from "../styles/dashboard.styles";

export function Dashboard() {
  const jobs = useApi(listJobs, []);
  const schedules = useApi(listSchedules, []);
  const workspaces = useApi(listWorkspaces, []);
  const classes = useStyles();

  return (
    <div className={classes.page}>
      <Text
        as="h1"
        size={600}
        weight="semibold"
        className={classes.heading}
        block
      >
        Dashboard
      </Text>

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
        <Text
          as="h2"
          size={200}
          weight="semibold"
          className={classes.sectionTitle}
          block
        >
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
                <a
                  key={job.id}
                  href={`/jobs/${job.id}`}
                  className={classes.jobRow}
                >
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
                <Text
                  size={300}
                  align="center"
                  block
                  style={{ padding: "1rem" }}
                >
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
