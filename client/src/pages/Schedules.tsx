// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { useCallback } from "react";
import {
  Button,
  Text,
  Card,
  Badge,
  Spinner,
} from "@fluentui/react-components";
import {
  ArrowClockwise24Regular,
  Play24Regular,
  Delete24Regular,
} from "@fluentui/react-icons";
import {
  listSchedules,
  deleteSchedule,
  triggerSchedule,
} from "../lib/api";
import { useApi } from "../hooks/useApi";
import { useStyles } from "../styles/schedules.styles";

export function Schedules() {
  const { data: schedules, loading, error, refetch } = useApi(
    listSchedules,
    [],
  );
  const classes = useStyles();

  const handleDelete = useCallback(
    async (id: string) => {
      await deleteSchedule(id);
      refetch();
    },
    [refetch],
  );

  const handleTrigger = useCallback(
    async (id: string) => {
      await triggerSchedule(id);
      refetch();
    },
    [refetch],
  );

  return (
    <div className={classes.page}>
      <div className={classes.toolbar}>
        <Text as="h1" size={600} weight="semibold">
          Schedules
        </Text>
        <Button
          appearance="primary"
          icon={<ArrowClockwise24Regular />}
          onClick={refetch}
        >
          Refresh
        </Button>
      </div>

      {loading && <Spinner size="small" label="Loading..." />}
      {error && (
        <Text size={300}>
          Unable to load schedules — backend may be offline.
        </Text>
      )}

      <div className={classes.list}>
        {(schedules ?? []).map((s) => (
          <Card key={s.id} size="small">
            <div className={classes.cardHeader}>
              <div className={classes.cardTitle}>
                <Text weight="semibold" size={300}>
                  {s.name}
                </Text>
                <Badge
                  appearance="filled"
                  color={s.enabled ? "success" : "informative"}
                  size="small"
                >
                  {s.enabled ? "Active" : "Paused"}
                </Badge>
              </div>
              <div className={classes.cardActions}>
                <Button
                  appearance="subtle"
                  size="small"
                  icon={<Play24Regular />}
                  onClick={() => handleTrigger(s.id)}
                >
                  Trigger
                </Button>
                <Button
                  appearance="subtle"
                  size="small"
                  icon={<Delete24Regular />}
                  onClick={() => handleDelete(s.id)}
                >
                  Delete
                </Button>
              </div>
            </div>
            <div className={classes.detailGrid}>
              <div>
                <Text size={100} weight="semibold" block>
                  CRON
                </Text>
                <Text font="monospace" size={200}>
                  {s.cron_expression}
                </Text>
              </div>
              <div>
                <Text size={100} weight="semibold" block>
                  WORKSPACE
                </Text>
                <Text size={200}>{s.workspace_id}</Text>
              </div>
              <div>
                <Text size={100} weight="semibold" block>
                  PLAYBOOK
                </Text>
                <Text size={200}>{s.playbook}</Text>
              </div>
              <div>
                <Text size={100} weight="semibold" block>
                  NEXT RUN
                </Text>
                <Text size={200}>
                  {s.next_run_time
                    ? new Date(s.next_run_time).toLocaleString()
                    : "—"}
                </Text>
              </div>
            </div>
          </Card>
        ))}
        {(schedules ?? []).length === 0 && !loading && (
          <Text size={300}>No schedules configured.</Text>
        )}
      </div>
    </div>
  );
}
