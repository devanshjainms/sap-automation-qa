// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import {
  Card,
  Text,
} from "@fluentui/react-components";
import { useStyles } from "../../styles/toolRenderers.styles";

interface ToolCallProps {
  name: string;
  status: "running" | "complete" | "error";
  args?: Record<string, unknown>;
  result?: unknown;
}

export function ToolCallCard({ name, status, args, result }: ToolCallProps) {
  const classes = useStyles();
  return (
    <Card className={classes.card} size="small">
      <div className={classes.header}>
        <span>
          {status === "complete" ? "✅" : status === "error" ? "❌" : "⏳"}
        </span>
        <Text font="monospace" size={200}>
          {name}
        </Text>
      </div>

      {status === "running" && args && (
        <pre className={classes.pre}>{JSON.stringify(args, null, 2)}</pre>
      )}

      {status === "complete" && result != null && (
        <ToolResult result={result} classes={classes} />
      )}
    </Card>
  );
}

function ToolResult({
  result,
  classes,
}: {
  result: unknown;
  classes: ReturnType<typeof useStyles>;
}) {
  if (typeof result === "string") {
    return <Text size={200}>{result}</Text>;
  }
  return (
    <pre className={classes.pre}>{JSON.stringify(result, null, 2)}</pre>
  );
}
