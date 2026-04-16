// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { Card, Text, Spinner, mergeClasses } from "@fluentui/react-components";
import { getHealth } from "../lib/api";
import { useApi } from "../hooks/useApi";
import type { HealthComponent } from "../lib/types";
import { useStyles } from "../styles/status.styles";
import { strings } from "../lib/strings";
import { SERVICE_KEYS, SERVICE_LABELS } from "../lib/constants";

export function Status() {
  const { data: health, loading, error } = useApi(getHealth, []);
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
        {strings.pages.status.title}
      </Text>

      {loading ? (
        <Spinner size="small" label={strings.pages.status.checking} />
      ) : (
        <div className={classes.list}>
          {SERVICE_KEYS.map((key) => {
            const comp: HealthComponent = error
              ? {
                  status: "unhealthy",
                  detail: strings.pages.status.backendUnreachable,
                }
              : (health?.components?.[key] ?? {
                  status: "unconfigured",
                  detail: strings.pages.status.notReported,
                });
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
