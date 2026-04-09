// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import {
  Button,
  Text,
  Spinner,
  TableBody,
  TableCell,
  TableRow,
  Table,
  TableHeader,
  TableHeaderCell,
} from "@fluentui/react-components";
import { ArrowClockwise24Regular } from "@fluentui/react-icons";
import { listJobs } from "../lib/api";
import { useApi } from "../hooks/useApi";
import { StatusBadge } from "../components/shared/StatusBadge";
import { useStyles } from "../styles/jobs.styles";

export function Jobs() {
  const { data: jobs, loading, error, refetch } = useApi(listJobs, []);
  const classes = useStyles();

  return (
    <div className={classes.page}>
      <div className={classes.toolbar}>
        <Text as="h1" size={600} weight="semibold">
          Jobs
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
        <Text size={300}>Unable to load jobs — backend may be offline.</Text>
      )}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHeaderCell>ID</TableHeaderCell>
            <TableHeaderCell>Workspace</TableHeaderCell>
            <TableHeaderCell>Playbook</TableHeaderCell>
            <TableHeaderCell>Status</TableHeaderCell>
            <TableHeaderCell>Created</TableHeaderCell>
          </TableRow>
        </TableHeader>
        <TableBody>
          {(jobs ?? []).map((job) => (
            <TableRow
              key={job.id}
              className={classes.row}
              onClick={() => (window.location.href = `/jobs/${job.id}`)}
            >
              <TableCell>
                <Text font="monospace" size={200}>
                  {job.id.slice(0, 8)}
                </Text>
              </TableCell>
              <TableCell>{job.workspace_id}</TableCell>
              <TableCell>{job.playbook}</TableCell>
              <TableCell>
                <StatusBadge status={job.status} />
              </TableCell>
              <TableCell>
                <Text size={200}>
                  {new Date(job.created_at).toLocaleString()}
                </Text>
              </TableCell>
            </TableRow>
          ))}
          {(jobs ?? []).length === 0 && !loading && (
            <TableRow>
              <TableCell colSpan={5}>
                <Text size={300} align="center" block>
                  No jobs found.
                </Text>
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}
