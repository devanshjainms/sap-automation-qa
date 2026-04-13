// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Human-in-the-loop hooks for the SAP agent.
 */

import { useHumanInTheLoop } from "@copilotkit/react-core/v2";
import type { ToolCallStatus } from "@copilotkitnext/core";
import { useState } from "react";
import { useHitlStyles } from "../styles/hitl.styles";

/**
 * Tools that require user approval are configured on the backend via
 * ``approval_mode`` on ``MCPStreamableHTTPTool`` and
 * ``require_confirmation=True`` on ``AgentFrameworkAgent``.

/* ------------------------------------------------------------------ */
/*  request_info — Agent finished autonomous turns                     */
/* ------------------------------------------------------------------ */

export function useRequestInfoHITL() {
  useHumanInTheLoop(
    {
      name: "request_info",
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
  useRequestInfoHITL();
}
