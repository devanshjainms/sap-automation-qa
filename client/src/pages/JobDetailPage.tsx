// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { useParams } from "react-router-dom";
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

export function JobDetailPage() {
  const { id } = useParams<{ id: string }>();
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
    if (id) getJobLog(id, 200).then(setLog);
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

  if (loading) return <Spinner size="small" label="Loading..." />;
  if (error) return <Text size={300}>Error: {error}</Text>;
  if (!job) return <Text size={300}>Job not found.</Text>;

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
            window.location.href = "/jobs";
          }}
          size="small"
        >
          Jobs
        </Button>
        <Text size={500} weight="semibold" font="monospace">
          {job.id.slice(0, 8)}
        </Text>
        <StatusBadge status={job.status} />
      </div>

      <Card className={classes.meta}>
        <MetaField
          label="Workspace"
          value={job.workspace_id}
          classes={classes}
        />
        <MetaField label="Playbook" value={job.playbook} classes={classes} />
        <MetaField
          label="Created"
          value={new Date(job.created_at).toLocaleString()}
          classes={classes}
        />
        <MetaField
          label="Started"
          value={
            job.started_at ? new Date(job.started_at).toLocaleString() : "—"
          }
          classes={classes}
        />
        <MetaField
          label="Completed"
          value={
            job.completed_at ? new Date(job.completed_at).toLocaleString() : "—"
          }
          classes={classes}
        />
        {job.error && (
          <MetaField label="Error" value={job.error} classes={classes} />
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
            {cancelling ? "Cancelling..." : "Cancel"}
          </Button>
        )}
        <Button
          appearance="secondary"
          icon={<DocumentText24Regular />}
          onClick={loadLog}
        >
          {log !== null ? "Refresh Log" : "Load Log"}
        </Button>
        <Button
          appearance="secondary"
          icon={<ArrowClockwise24Regular />}
          onClick={refetch}
        >
          Refresh
        </Button>
      </div>

      {log !== null && (
        <div className={classes.logBox}>{log || "(empty log)"}</div>
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
