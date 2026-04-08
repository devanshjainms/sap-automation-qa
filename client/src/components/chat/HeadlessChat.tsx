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
import { useEffect, useRef } from "react";
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
 */
function toAgMessages(messages: Message[]): AGMessage[] {
  const result: AGMessage[] = [];
  let seq = 0;

  for (const msg of messages) {
    if (msg.role === "user") {
      result.push({ id: msg.id, role: "user", content: msg.content });
      continue;
    }

    // No parts → simple text-only assistant message (legacy / plain).
    if (!msg.parts?.length) {
      result.push({
        id: msg.id,
        role: "assistant",
        content: msg.content,
      } as AGMessage);
      continue;
    }

    // Walk parts in order, grouping text + following tool call.
    let pendingText = "";
    for (const part of msg.parts) {
      if (part.type === "text") {
        // Accumulate text until we hit a tool call or the end.
        pendingText += (pendingText ? "\n\n" : "") + part.content;
      } else if (part.type === "tool_call") {
        const tcId = `${msg.id}-tc-${seq}`;
        const trId = `${msg.id}-tr-${seq}`;
        seq++;

        // Emit assistant message with accumulated text + this tool call.
        result.push({
          id: `${msg.id}-a-${seq}`,
          role: "assistant",
          content: pendingText,
          toolCalls: [
            {
              id: tcId,
              type: "function" as const,
              function: {
                name: part.toolCall.name,
                arguments: part.toolCall.args,
              },
            },
          ],
        } as AGMessage);
        pendingText = "";

        // Emit tool result.
        result.push({
          id: trId,
          role: "tool",
          content: part.toolCall.result || "",
          toolCallId: tcId,
        } as AGMessage);
      }
    }

    // Trailing text after the last tool call.
    if (pendingText) {
      result.push({
        id: `${msg.id}-tail`,
        role: "assistant",
        content: pendingText,
      } as AGMessage);
    }
  }
  return result;
}

/* ── Inner chat (must be inside CopilotKit) ────────────── */

function SapChatInner() {
  const { conversationId } = useParams<{ conversationId?: string }>();
  const classes = useStyles();
  const { agent } = useAgent({ agentId: "sap-agent" });

  /* CopilotKit built-in tool card — clickable, expandable. Dark mode via CSS. */
  useDefaultRenderTool();

  /* ── Streaming diagnostic: log every message update ── */
  const renderCountRef = useRef(0);
  useEffect(() => {
    const sub = agent.subscribe({
      onMessagesChanged: ({ messages }) => {
        renderCountRef.current++;
        const last = messages[messages.length - 1];
        const contentLen =
          last && "content" in last && typeof last.content === "string"
            ? last.content.length
            : 0;
        console.log(
          `[SSE-DIAG] #${renderCountRef.current} msgs=${messages.length} ` +
            `lastRole=${last?.role ?? "?"} contentLen=${contentLen} ` +
            `t=${Date.now()}`,
        );
      },
    });
    return () => sub.unsubscribe();
  }, [agent]);

  /* Load historical messages from the REST API when resuming a thread */
  useEffect(() => {
    if (!conversationId) return;
    let cancelled = false;
    getConversation(conversationId)
      .then((conv) => {
        if (cancelled) return;
        if (!conv.messages?.length) {
          // No messages yet — don't call setMessages so CopilotKit
          // shows the welcome state instead of an empty chat.
          return;
        }
        const agMsgs = toAgMessages(conv.messages);
        if (agMsgs.length > 0) {
          agent.setMessages(agMsgs);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          // 404 = conversation deleted or from previous DB; ignore.
          console.warn("Could not load conversation history:", err);
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
