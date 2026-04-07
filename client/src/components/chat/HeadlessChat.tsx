// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Chat component using CopilotKit's built-in ``CopilotChat`` for message
 * handling and tool-call rendering.  ``useDefaultRenderTool`` enables
 * CopilotKit's native expandable tool-call cards for all backend tools.
 *
 * Historical messages are loaded from the REST API on mount and fed to
 * CopilotKit via ``agent.setMessages()``.  AG-UI handles only real-time
 * agent execution — it is not responsible for fetching conversation history.
 */

import {
  CopilotKitProvider,
  CopilotChat,
  HttpAgent,
  useAgent,
  useAgentContext,
  useDefaultRenderTool,
} from "@copilotkit/react-core/v2";
import type { Message as AGMessage } from "@ag-ui/core";
import { useEffect } from "react";
import { useParams } from "react-router-dom";
import { getConversation } from "../../lib/api";
import type { Message } from "../../lib/types";
import { useStyles } from "../../styles/headlessChat.styles";

const sapAgent = new HttpAgent({
  url: "/ag-ui",
  agentId: "sap-agent",
});

/**
 * Convert REST API messages to AG-UI message format for CopilotKit.
 *
 * Assistant messages with ``toolCalls`` produce an ``AssistantMessage``
 * with a ``toolCalls`` array followed by individual ``ToolMessage``
 * entries — matching the AG-UI protocol replay format so CopilotKit
 * renders the expandable tool-call cards.
 */
function toAgMessages(messages: Message[]): AGMessage[] {
  const result: AGMessage[] = [];
  for (const msg of messages) {
    if (msg.role === "user") {
      result.push({ id: msg.id, role: "user", content: msg.content });
    } else if (msg.role === "assistant") {
      const toolCalls = msg.toolCalls?.map((tc, i) => ({
        id: `${msg.id}-tc-${i}`,
        type: "function" as const,
        function: { name: tc.name, arguments: tc.args },
      }));
      result.push({
        id: msg.id,
        role: "assistant",
        content: msg.content,
        ...(toolCalls?.length ? { toolCalls } : {}),
      } as AGMessage);
      if (msg.toolCalls?.length) {
        for (let i = 0; i < msg.toolCalls.length; i++) {
          result.push({
            id: `${msg.id}-tr-${i}`,
            role: "tool",
            content: msg.toolCalls[i].result || "",
            toolCallId: `${msg.id}-tc-${i}`,
          } as AGMessage);
        }
      }
    }
  }
  return result;
}

/* ── Inner chat (must be inside CopilotKit) ────────────── */

function SapChatInner() {
  const { conversationId } = useParams<{ conversationId?: string }>();
  const classes = useStyles();
  const { agent } = useAgent({ agentId: "sap-agent" });

  /* Enable CopilotKit's built-in expandable tool-call cards for all tools */
  useDefaultRenderTool();

  /* Load historical messages from the REST API when resuming a thread */
  useEffect(() => {
    if (!conversationId) return;
    let cancelled = false;
    getConversation(conversationId)
      .then((conv) => {
        if (cancelled || !conv.messages?.length) return;
        const agMsgs = toAgMessages(conv.messages);
        if (agMsgs.length > 0) {
          agent.setMessages(agMsgs);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          console.error("Failed to load conversation history:", err);
        }
      });
    return () => { cancelled = true; };
  }, [conversationId, agent]);

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
        threadId={conversationId}
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
