// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Human-in-the-loop hooks for the SAP agent.
 *
 * Uses ``useHumanInTheLoop`` following the official CopilotKit + Microsoft
 * Agent Framework pattern:
 * @see https://docs.copilotkit.ai/microsoft-agent-framework/human-in-the-loop
 */

import { useHumanInTheLoop } from "@copilotkit/react-core/v2";
import type { ToolCallStatus } from "@copilotkitnext/core";
import { useState } from "react";
import { z } from "zod";
import { useHitlStyles } from "../styles/hitl.styles";
import { AGENT_ID } from "../lib/constants";

/* ------------------------------------------------------------------ */
/*  confirm_changes — approval gate for destructive MCP tools          */
/* ------------------------------------------------------------------ */

const confirmChangesSchema = z.object({
  function_name: z.string(),
  function_call_id: z.string(),
  function_arguments: z.record(z.string(), z.unknown()).optional(),
  steps: z.array(
    z.object({
      description: z.string(),
      status: z.string(),
    }),
  ),
});

type ConfirmChangesArgs = z.infer<typeof confirmChangesSchema>;

function useConfirmChangesHITL() {
  useHumanInTheLoop(
    {
      name: "confirm_changes",
      agentId: AGENT_ID,
      description: "Ask user for approval before executing a tool.",
      parameters: confirmChangesSchema,
      render: ConfirmChangesRenderer as any,
    },
    [],
  );
}

function ConfirmChangesRenderer({
  args,
  status,
  result,
  respond,
}: {
  name: string;
  description: string;
  args: Partial<ConfirmChangesArgs>;
  status: ToolCallStatus;
  result: string | undefined;
  respond: ((result: unknown) => Promise<void>) | undefined;
}) {
  const classes = useHitlStyles();
  const [decided, setDecided] = useState<"approved" | "rejected" | null>(
    null,
  );

  const funcName = args.function_name ?? "Action";
  const funcArgs = args.function_arguments ?? {};
  const steps = args.steps ?? [];
  const argLines = Object.entries(funcArgs).map(
    ([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`,
  );

  if (status === "complete" || decided) {
    const label = decided ?? (result?.includes("true") ? "approved" : "rejected");
    return (
      <div className={classes.completed}>
        <span className={classes.completedText}>
          {label === "approved" ? "✓ Approved" : "✗ Rejected"}: {funcName}
        </span>
      </div>
    );
  }

  if (!respond) {
    return (
      <div className={classes.container}>
        <span className={classes.subtitle}>Preparing approval…</span>
      </div>
    );
  }

  const handleApprove = async () => {
    setDecided("approved");
    await respond(
      JSON.stringify({
        accepted: true,
        function_call_id: args.function_call_id,
        steps: steps.map((s) => ({ ...s, status: "enabled" })),
      }),
    );
  };

  const handleReject = async () => {
    setDecided("rejected");
    await respond(
      JSON.stringify({
        accepted: false,
        function_call_id: args.function_call_id,
        steps: steps.map((s) => ({ ...s, status: "disabled" })),
      }),
    );
  };

  return (
    <div className={classes.container}>
      <div className={classes.heading}>Approve: {funcName}</div>
      {argLines.length > 0 && (
        <div className={classes.argsList}>
          {argLines.map((line) => (
            <div key={line} className={classes.argRow}>
              <span className={classes.argValue}>{line}</span>
            </div>
          ))}
        </div>
      )}
      <div className={classes.buttonRow}>
        <button type="button" className={classes.primaryBtn} onClick={handleApprove}>
          Approve
        </button>
        <button type="button" className={classes.secondaryBtn} onClick={handleReject}>
          Reject
        </button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  request_info — Agent finished autonomous turns                     */
/* ------------------------------------------------------------------ */

export function useRequestInfoHITL() {
  useHumanInTheLoop(
    {
      name: "request_info",
      agentId: AGENT_ID,
      description:
        "The agent has completed its current investigation and is " +
        "asking whether you'd like it to continue or if you're done.",
      render: RequestInfoRenderer as any,
    },
    [],
  );
}

function RequestInfoRenderer({
  status,
  respond,
  result,
}: {
  name: string;
  description: string;
  args: Record<string, unknown>;
  status: ToolCallStatus;
  result: string | undefined;
  respond: ((result: unknown) => Promise<void>) | undefined;
}) {
  const classes = useHitlStyles();
  const [followUp, setFollowUp] = useState("");

  if (status === "complete" || result) {
    return (
      <div className={classes.completed}>
        <span className={classes.completedText}>
          ✓ {result || "Conversation continued"}
        </span>
      </div>
    );
  }

  if (!respond) {
    return (
      <div className={classes.container}>
        <span className={classes.subtitle}>Agent is preparing…</span>
      </div>
    );
  }

  const handleContinue = async () => {
    const text = followUp.trim() || "Continue the investigation.";
    await respond(text);
  };

  const handleDone = async () => {
    await respond("The investigation is complete. No further action needed.");
  };

  return (
    <div className={classes.container}>
      <div className={classes.heading}>
        The agent has finished its current analysis.
      </div>
      <div className={classes.subtitle}>
        You can provide additional direction or end the conversation.
      </div>
      <input
        type="text"
        placeholder="Ask a follow-up question… (optional)"
        value={followUp}
        onChange={(e) => setFollowUp(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") handleContinue();
        }}
        className={classes.input}
      />
      <div className={classes.buttonRow}>
        <button
          type="button"
          className={classes.primaryBtn}
          onClick={handleContinue}
        >
          {followUp.trim() ? "Send & Continue" : "Continue"}
        </button>
        <button
          type="button"
          className={classes.secondaryBtn}
          onClick={handleDone}
        >
          Done
        </button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Master hook — registers all HITL handlers                          */
/* ------------------------------------------------------------------ */

/**
 * Call this once inside the CopilotKit provider to register all
 * human-in-the-loop handlers.  New handlers (test consent, command
 * approval, etc.) should be added here.
 */
export function useAgentHITL() {
  useConfirmChangesHITL();
  useRequestInfoHITL();
}
