// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Chat component using CopilotKit's built-in ``CopilotChat`` for message
 * handling and tool-call rendering. Tool calls use CopilotKit's native
 * ``WildcardToolCallRender`` which provides a compact, Copilot-like UI.
 */

import {
  CopilotKitProvider,
  CopilotChat,
  HttpAgent,
  useAgentContext,
} from "@copilotkit/react-core/v2";
import { useParams } from "react-router-dom";
import { useStyles } from "../../styles/headlessChat.styles";

const sapAgent = new HttpAgent({
  url: "/ag-ui",
  agentId: "sap-agent",
});

/* ── Inner chat (must be inside CopilotKit) ────────────── */

function SapChatInner() {
  const { conversationId } = useParams<{ conversationId?: string }>();
  const classes = useStyles();

  /* Provide app context to the agent */
  useAgentContext({
    description: "Current SAP workspace context",
    value: conversationId
      ? `Active conversation: ${conversationId}`
      : "New conversation — no thread selected",
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

/* ── Exported wrapper — owns provider ───────────────────── */

export function SapChat() {
  const { conversationId } = useParams<{ conversationId?: string }>();

  return (
    <CopilotKitProvider
      key={conversationId ?? "new"}
      agents__unsafe_dev_only={{ "sap-agent": sapAgent }}
      showDevConsole={false}
    >
      <SapChatInner />
    </CopilotKitProvider>
  );
}
