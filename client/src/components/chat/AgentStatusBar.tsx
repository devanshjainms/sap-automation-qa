// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Status bar that renders real-time agent state from AG-UI
 * ``STATE_SNAPSHOT`` events.  Shows the current phase (classifying,
 * thinking, calling_tool, responding, complete) and active tool calls.
 *
 * Subscribes to ``agent.state`` via ``onStateChanged`` from CopilotKit v2.
 */

import { useAgent, UseAgentUpdate } from "@copilotkit/react-core/v2";
import { makeStyles, tokens, Spinner } from "@fluentui/react-components";
import { AGENT_ID } from "../../lib/constants";

/* ── Styles ──────────────────────────────────────────────── */

const useStyles = makeStyles({
  bar: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    padding: "6px 14px",
    fontSize: "12px",
    color: tokens.colorNeutralForeground3,
    borderBottom: `1px solid ${tokens.colorNeutralStroke2}`,
    minHeight: "28px",
    flexShrink: 0,
  },
  phase: {
    fontWeight: 600,
    textTransform: "capitalize" as const,
  },
  toolChip: {
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    padding: "1px 8px",
    borderRadius: "10px",
    backgroundColor: tokens.colorNeutralBackground3,
    fontSize: "11px",
  },
  toolDone: {
    backgroundColor: tokens.colorPaletteGreenBackground2,
    color: tokens.colorPaletteGreenForeground2,
  },
  toolActive: {
    backgroundColor: tokens.colorPaletteBlueBorderActive,
    color: tokens.colorNeutralForegroundOnBrand,
  },
  hidden: {
    display: "none",
  },
});

/* ── Types ───────────────────────────────────────────────── */

interface ToolInfo {
  name: string;
  status: "in_progress" | "completed";
}

interface AgentState {
  status?: string;
  intent?: string;
  active_agent?: string;
  tools?: ToolInfo[];
  tool_activity?: Record<string, unknown>;
}

/* ── Status label mapping ────────────────────────────────── */

const STATUS_LABELS: Record<string, string> = {
  classifying: "Classifying intent…",
  thinking: "Thinking…",
  calling_tool: "Calling tool…",
  responding: "Responding…",
  complete: "Done",
};

/* ── Component ───────────────────────────────────────────── */

export function AgentStatusBar() {
  const classes = useStyles();
  const { agent } = useAgent({
    agentId: AGENT_ID,
    updates: [UseAgentUpdate.OnStateChanged],
  });

  const state = (agent?.state ?? {}) as AgentState;
  const { status, intent, tools, tool_activity } = state;

  // Show bar whenever there's any state (status from our snapshots
  // or tool_activity from predictive STATE_DELTA events).
  const hasActivity =
    (status && status !== "complete") ||
    (tool_activity && Object.keys(tool_activity).length > 0);

  if (!hasActivity) {
    return null;
  }

  const label = status ? (STATUS_LABELS[status] ?? status) : "Working…";

  return (
    <div className={classes.bar}>
      <Spinner size="tiny" />
      <span className={classes.phase}>{label}</span>
      {intent && <span>({intent})</span>}
      {tools && tools.length > 0 && (
        <>
          <span>·</span>
          {tools.map((t, i) => (
            <span
              key={`${t.name}-${i}`}
              className={`${classes.toolChip} ${
                t.status === "completed" ? classes.toolDone : classes.toolActive
              }`}
            >
              {t.status === "in_progress" ? "⏳" : "✓"} {t.name}
            </span>
          ))}
        </>
      )}
    </div>
  );
}
