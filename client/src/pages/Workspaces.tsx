// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import {
  Button,
  Text,
  Card,
  Badge,
  Spinner,
} from "@fluentui/react-components";
import {
  ArrowClockwise24Regular,
  BuildingMultiple24Regular,
} from "@fluentui/react-icons";
import { listWorkspaces } from "../lib/api";
import { useApi } from "../hooks/useApi";
import { useStyles } from "../styles/workspaces.styles";

export function Workspaces() {
  const { data: workspaces, loading, error, refetch } = useApi(
    listWorkspaces,
    [],
  );
  const classes = useStyles();

  return (
    <div className={classes.page}>
      <div className={classes.toolbar}>
        <Text as="h1" size={600} weight="semibold">
          Workspaces
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
          Unable to load workspaces — backend may be offline.
        </Text>
      )}

      <div className={classes.grid}>
        {(workspaces ?? []).map((ws) => (
          <Card key={ws.id} className={classes.card} size="small">
            <div className={classes.cardHeader}>
              <BuildingMultiple24Regular />
              <Text weight="semibold" size={300}>
                {ws.id}
              </Text>
            </div>
            <Text
              font="monospace"
              size={100}
              className={classes.path}
            >
              {ws.path}
            </Text>
            <Badge
              appearance="filled"
              color={ws.config_exists ? "success" : "warning"}
              size="small"
            >
              {ws.config_exists ? "Configured" : "No Config"}
            </Badge>
          </Card>
        ))}
        {(workspaces ?? []).length === 0 && !loading && (
          <Text size={300}>No workspaces found.</Text>
        )}
      </div>
    </div>
  );
}
