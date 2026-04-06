// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Chat component using CopilotKit's ``CopilotChat`` for message handling
 * with ``useDefaultRenderTool`` to render all tool calls using metadata
 * fetched from the backend MCP registry.
 *
 * Tool titles, icons, parameter schemas, and annotations are the single
 * source of truth defined in the backend ``@mcp.tool()`` decorators.
 */

import {
  CopilotChat,
  useDefaultRenderTool,
  useConfigureSuggestions,
  useAgentContext,
} from "@copilotkit/react-core/v2";
import { useParams } from "react-router-dom";
import {
  Spinner,
  Text,
  Badge,
  Tooltip,
} from "@fluentui/react-components";
import { useStyles } from "../../styles/headlessChat.styles";
import { useToolRegistry } from "../../hooks/useToolRegistry";
import type { ToolMeta } from "../../lib/types";

/* ── Tool call card ──────────────────────────────────────── */

/** Props forwarded directly from CopilotKit's useDefaultRenderTool callback. */
interface ToolCallCardProps {
  name: string;
  parameters: unknown;
  status: "inProgress" | "executing" | "complete";
  result: string | undefined;
  meta?: ToolMeta;
}

function SapToolCallCard({ name, parameters, status, result, meta }: ToolCallCardProps) {
  const classes = useStyles();
  const label = meta?.title ?? name;
  const iconSrc = meta?.icons?.[0]?.src;
  const isDestructive = meta?.annotations?.destructiveHint === true;
  const paramProps = meta?.parameters?.properties;
  const args =
    parameters && typeof parameters === "object"
      ? (parameters as Record<string, unknown>)
      : null;

  const badgeColor =
    status === "complete"
      ? "success"
      : status === "executing"
        ? "brand"
        : "informative";
  const badgeLabel =
    status === "inProgress"
      ? "preparing"
      : status === "executing"
        ? "running"
        : "complete";

  return (
    <div className={classes.toolCallCard}>
      <div className={classes.toolCallHeader}>
        {iconSrc ? (
          <img src={iconSrc} alt="" width={16} height={16} />
        ) : (
          <span>⚙️</span>
        )}
        <Tooltip content={meta?.description ?? name} relationship="label">
          <Text size={200} weight="semibold">
            {label}
          </Text>
        </Tooltip>
        {isDestructive && (
          <Badge appearance="tint" color="warning" size="small">
            destructive
          </Badge>
        )}
        <Badge appearance="filled" color={badgeColor} size="small">
          {badgeLabel}
        </Badge>
        {status !== "complete" && <Spinner size="tiny" />}
      </div>
      {args && Object.keys(args).length > 0 && (
        <pre className={classes.toolCallArgs}>
          {Object.entries(args)
            .map(([k, v]) => {
              const paramTitle = paramProps?.[k]?.title ?? k;
              const val =
                typeof v === "string" ? v : JSON.stringify(v, null, 2);
              return `${paramTitle}: ${val}`;
            })
            .join("\n")}
        </pre>
      )}
      {status === "complete" && result != null && (
        <pre className={classes.toolCallArgs}>{result}</pre>
      )}
    </div>
  );
}

/* ── Main chat component ─────────────────────────────────── */

export function SapChat() {
  const { conversationId } = useParams<{ conversationId?: string }>();
  const classes = useStyles();
  const registry = useToolRegistry();

  /* Render all tool calls using backend MCP metadata */
  useDefaultRenderTool(
    {
      render: ({ name, parameters, status, result }) => (
        <SapToolCallCard
          name={name}
          parameters={parameters}
          status={status}
          result={result}
          meta={registry.get(name)}
        />
      ),
    },
    [registry],
  );

  /* Provide app context to the agent */
  useAgentContext({
    description: "Current SAP workspace context",
    value: conversationId
      ? `Active conversation: ${conversationId}`
      : "New conversation — no thread selected",
  });

  /* Quick-start suggestions for SAP tasks */
  useConfigureSuggestions({
    instructions:
      "Suggest 3 helpful SAP triage and testing actions: " +
      "investigating cluster health, running HA tests, or checking system status.",
    available: "always",
  });

  return (
    <div className={classes.container}>
      <CopilotChat
        agentId="sap-agent"
        className="copilot-chat-fullpage"
        labels={{
          modalHeaderTitle: "SAP Assistant",
          welcomeMessageText:
            "How can I help you with your SAP systems today?",
          chatInputPlaceholder: "Ask about SAP systems...",
        }}
      />
    </div>
  );
}
