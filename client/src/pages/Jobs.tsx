// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { useNavigate } from "react-router-dom";
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
import { strings } from "../lib/strings";
import { JOB_ID_DISPLAY_LENGTH } from "../lib/constants";

export function Jobs() {
  const { data: jobs, loading, error, refetch } = useApi(listJobs, []);
  const classes = useStyles();
  const navigate = useNavigate();

  return (
    <div className={classes.page}>
      <div className={classes.toolbar}>
        <Text as="h1" size={600} weight="semibold">
          {strings.pages.jobs.title}
        </Text>
        <Button
          appearance="primary"
          icon={<ArrowClockwise24Regular />}
          onClick={refetch}
        >
          {strings.pages.jobs.refresh}
        </Button>
      </div>

      {loading && <Spinner size="small" label={strings.shared.loading} />}
      {error && <Text size={300}>{strings.pages.jobs.loadError}</Text>}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHeaderCell>{strings.pages.jobs.columns.id}</TableHeaderCell>
            <TableHeaderCell>
              {strings.pages.jobs.columns.workspace}
            </TableHeaderCell>
            <TableHeaderCell>
              {strings.pages.jobs.columns.playbook}
            </TableHeaderCell>
            <TableHeaderCell>
              {strings.pages.jobs.columns.status}
            </TableHeaderCell>
            <TableHeaderCell>
              {strings.pages.jobs.columns.created}
            </TableHeaderCell>
          </TableRow>
        </TableHeader>
        <TableBody>
          {(jobs ?? []).map((job) => (
            <TableRow
              key={job.id}
              className={classes.row}
              onClick={() => navigate(`/jobs/${job.id}`)}
            >
              <TableCell>
                <Text font="monospace" size={200}>
                  {job.id.slice(0, JOB_ID_DISPLAY_LENGTH)}
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
                  {strings.pages.jobs.noJobs}
                </Text>
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}
