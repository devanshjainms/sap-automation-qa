// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import {
  Card,
  Text,
  Spinner,
  mergeClasses,
} from "@fluentui/react-components";
import { getHealth } from "../lib/api";
import { useApi } from "../hooks/useApi";
import type { HealthComponent } from "../lib/types";
import { useStyles } from "../styles/status.styles";

const SERVICE_KEYS = ["core", "mcp", "llm", "ollama", "azure_mcp"] as const;

const SERVICE_LABELS: Record<string, string> = {
  core: "Core API",
  mcp: "MCP Server",
  llm: "LLM Connection",
  ollama: "Ollama (Embeddings)",
  azure_mcp: "Azure MCP",
};

export function Status() {
  const { data: health, loading, error } = useApi(getHealth, []);
  const classes = useStyles();

  return (
    <div className={classes.page}>
      <Text as="h1" size={600} weight="semibold" className={classes.heading} block>
        Service Status
      </Text>

      {loading ? (
        <Spinner size="small" label="Checking services..." />
      ) : (
        <div className={classes.list}>
          {SERVICE_KEYS.map((key) => {
            const comp: HealthComponent = error
              ? { status: "unhealthy", detail: "Backend unreachable" }
              : health?.components?.[key] ?? {
                  status: "unconfigured",
                  detail: "Not reported",
                };
            const dotClass =
              comp.status === "healthy"
                ? classes.dotHealthy
                : comp.status === "unhealthy"
                  ? classes.dotUnhealthy
                  : classes.dotDefault;
            const isDown = comp.status === "unhealthy";

            return (
              <Card key={key} className={classes.card} size="small">
                <div className={classes.cardRow}>
                  <span className={mergeClasses(classes.dot, dotClass)} />
                  <div className={classes.info}>
                    <Text weight="semibold" size={300}>
                      {SERVICE_LABELS[key] ?? key}
                    </Text>
                    {!isDown && (
                      <Text size={200}>{comp.detail ?? comp.status}</Text>
                    )}
                  </div>
                  {comp.latency_ms != null && (
                    <Text size={200} className={classes.latency}>
                      {Math.round(comp.latency_ms)} ms
                    </Text>
                  )}
                </div>
                {isDown && comp.detail && (
                  <Text size={200} className={classes.errorDetail} block>
                    {comp.detail}
                  </Text>
                )}
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
