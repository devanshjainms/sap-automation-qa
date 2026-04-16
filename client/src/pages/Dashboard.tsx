// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { useNavigate } from "react-router-dom";
import { Card, Text, Spinner, mergeClasses } from "@fluentui/react-components";
import { listJobs, listSchedules, listWorkspaces } from "../lib/api";
import { useApi } from "../hooks/useApi";
import { StatusBadge } from "../components/shared/StatusBadge";
import { useStyles } from "../styles/dashboard.styles";
import { strings } from "../lib/strings";
import { RECENT_JOBS_COUNT, JOB_ID_DISPLAY_LENGTH } from "../lib/constants";

export function Dashboard() {
  const jobs = useApi(listJobs, []);
  const schedules = useApi(listSchedules, []);
  const workspaces = useApi(listWorkspaces, []);
  const classes = useStyles();
  const navigate = useNavigate();

  return (
    <div className={classes.page}>
      <Text
        as="h1"
        size={600}
        weight="semibold"
        className={classes.heading}
        block
      >
        {strings.pages.dashboard.title}
      </Text>

      {/* Summary cards */}
      <div className={mergeClasses(classes.grid3, classes.section)}>
        <SummaryCard
          label={strings.nav.jobs}
          value={jobs.error ? strings.shared.emptyValue : (jobs.data?.length ?? strings.shared.emptyValue)}
          loading={jobs.loading}
          onNavigate={() => navigate("/jobs")}
          classes={classes}
        />
        <SummaryCard
          label={strings.nav.schedules}
          value={schedules.error ? strings.shared.emptyValue : (schedules.data?.length ?? strings.shared.emptyValue)}
          loading={schedules.loading}
          onNavigate={() => navigate("/schedules")}
          classes={classes}
        />
        <SummaryCard
          label={strings.nav.workspaces}
          value={workspaces.error ? strings.shared.emptyValue : (workspaces.data?.length ?? strings.shared.emptyValue)}
          loading={workspaces.loading}
          onNavigate={() => navigate("/workspaces")}
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
          {strings.pages.dashboard.recentJobs}
        </Text>
        {jobs.loading ? (
          <Spinner size="small" label={strings.shared.loading} />
        ) : jobs.error ? (
          <Text size={300}>{strings.pages.jobs.loadError}</Text>
        ) : (
          <Card>
            <div className={classes.jobList}>
              {(jobs.data ?? []).slice(0, RECENT_JOBS_COUNT).map((job) => (
                <a
                  key={job.id}
                  href={`/jobs/${job.id}`}
                  className={classes.jobRow}
                  onClick={(e) => {
                    e.preventDefault();
                    navigate(`/jobs/${job.id}`);
                  }}
                >
                  <div className={classes.jobMeta}>
                    <Text font="monospace" size={200}>
                      {job.id.slice(0, JOB_ID_DISPLAY_LENGTH)}
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
                  className={classes.emptyJobsText}
                >
                  {strings.pages.dashboard.noJobs}
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
  onNavigate,
  classes,
}: {
  label: string;
  value: string | number;
  loading: boolean;
  onNavigate: () => void;
  classes: ReturnType<typeof useStyles>;
}) {
  return (
    <Card
      className={classes.summaryCard}
      size="small"
      onClick={onNavigate}
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
