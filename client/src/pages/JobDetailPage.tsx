// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { useParams, useNavigate } from "react-router-dom";
import { useCallback, useState } from "react";
import { Button, Text, Card, Spinner } from "@fluentui/react-components";
import {
  ArrowLeft24Regular,
  ArrowClockwise24Regular,
  Dismiss24Regular,
  DocumentText24Regular,
} from "@fluentui/react-icons";
import { getJob, getJobLog, cancelJob } from "../lib/api";
import { useApi } from "../hooks/useApi";
import { StatusBadge } from "../components/shared/StatusBadge";
import { useStyles } from "../styles/jobDetailPage.styles";
import { strings } from "../lib/strings";
import { JOB_ID_DISPLAY_LENGTH, JOB_LOG_TAIL_LINES } from "../lib/constants";

export function JobDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const {
    data: job,
    loading,
    error,
    refetch,
  } = useApi(() => getJob(id!), [id]);
  const [log, setLog] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const classes = useStyles();

  const loadLog = useCallback(() => {
    if (id) getJobLog(id, JOB_LOG_TAIL_LINES).then(setLog);
  }, [id]);

  const handleCancel = useCallback(async () => {
    if (!id) return;
    setCancelling(true);
    try {
      await cancelJob(id);
      refetch();
    } finally {
      setCancelling(false);
    }
  }, [id, refetch]);

  if (loading) return <Spinner size="small" label={strings.shared.loading} />;
  if (error) return <Text size={300}>{error}</Text>;
  if (!job) return <Text size={300}>{strings.pages.jobDetail.notFound}</Text>;

  return (
    <div className={classes.page}>
      <div className={classes.breadcrumb}>
        <Button
          as="a"
          appearance="subtle"
          icon={<ArrowLeft24Regular />}
          href="/jobs"
          onClick={(e) => {
            e.preventDefault();
            navigate("/jobs");
          }}
          size="small"
        >
          {strings.pages.jobs.title}
        </Button>
        <Text size={500} weight="semibold" font="monospace">
          {job.id.slice(0, JOB_ID_DISPLAY_LENGTH)}
        </Text>
        <StatusBadge status={job.status} />
      </div>

      <Card className={classes.meta}>
        <MetaField
          label={strings.pages.jobDetail.fields.workspace}
          value={job.workspace_id}
          classes={classes}
        />
        <MetaField
          label={strings.pages.jobDetail.fields.playbook}
          value={job.playbook}
          classes={classes}
        />
        <MetaField
          label={strings.pages.jobDetail.fields.created}
          value={new Date(job.created_at).toLocaleString()}
          classes={classes}
        />
        <MetaField
          label={strings.pages.jobDetail.fields.started}
          value={
            job.started_at
              ? new Date(job.started_at).toLocaleString()
              : strings.shared.emptyValue
          }
          classes={classes}
        />
        <MetaField
          label={strings.pages.jobDetail.fields.completed}
          value={
            job.completed_at
              ? new Date(job.completed_at).toLocaleString()
              : strings.shared.emptyValue
          }
          classes={classes}
        />
        {job.error && (
          <MetaField
            label={strings.pages.jobDetail.fields.error}
            value={job.error}
            classes={classes}
          />
        )}
      </Card>

      <div className={classes.actions}>
        {job.status === "running" && (
          <Button
            appearance="primary"
            icon={<Dismiss24Regular />}
            onClick={handleCancel}
            disabled={cancelling}
          >
            {cancelling
              ? strings.pages.jobDetail.cancelling
              : strings.pages.jobDetail.cancel}
          </Button>
        )}
        <Button
          appearance="secondary"
          icon={<DocumentText24Regular />}
          onClick={loadLog}
        >
          {log !== null
            ? strings.pages.jobDetail.refreshLog
            : strings.pages.jobDetail.loadLog}
        </Button>
        <Button
          appearance="secondary"
          icon={<ArrowClockwise24Regular />}
          onClick={refetch}
        >
          {strings.pages.jobDetail.refresh}
        </Button>
      </div>

      {log !== null && (
        <div className={classes.logBox}>
          {log || strings.pages.jobDetail.emptyLog}
        </div>
      )}
    </div>
  );
}

function MetaField({
  label,
  value,
  classes,
}: {
  label: string;
  value: string;
  classes: ReturnType<typeof useStyles>;
}) {
  return (
    <div>
      <Text size={100} weight="semibold" className={classes.fieldLabel}>
        {label.toUpperCase()}
      </Text>
      <Text size={300}>{value}</Text>
    </div>
  );
}
