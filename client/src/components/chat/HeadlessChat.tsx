// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Chat component using CopilotKit's built-in ``CopilotChat`` for message
 * handling and tool-call rendering.  ``useDefaultRenderTool`` enables
 * CopilotKit's native expandable tool-call cards for all backend tools.
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
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { getConversation } from "../../lib/api";
import type { Message } from "../../lib/types";
import { addOptimisticConversation } from "../../lib/conversationEvents";
import { useStyles } from "../../styles/headlessChat.styles";
import { useAgentHITL } from "../../hooks/useAgentHITL";

const sapAgent = new HttpAgent({
  url: "/ag-ui",
  agentId: "sap-agent",
});

interface ReasoningMsg {
  id: string;
  content?: string;
}

function ReasoningMessage({
  message,
  messages,
  isRunning,
}: {
  message: ReasoningMsg;
  messages: ReasoningMsg[];
  isRunning: boolean;
}) {
  const isLatest = messages?.[messages.length - 1]?.id === message.id;
  const isStreaming = !!(isRunning && isLatest);
  const hasContent = !!(message.content && message.content.length > 0);
  const [open, setOpen] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef<number | null>(null);

  useEffect(() => {
    if (isStreaming && startRef.current === null) startRef.current = Date.now();
    if (!isStreaming && startRef.current !== null) {
      setElapsed((Date.now() - startRef.current) / 1000);
      return;
    }
    if (!isStreaming) return;
    const t = setInterval(() => {
      if (startRef.current !== null)
        setElapsed((Date.now() - startRef.current) / 1000);
    }, 1000);
    return () => clearInterval(t);
  }, [isStreaming]);

  useEffect(() => {
    if (isStreaming) setOpen(true);
    else setOpen(false);
  }, [isStreaming]);

  if (!hasContent && !isStreaming) return null;

  const secs = Math.round(elapsed);
  const label = isStreaming
    ? "Thinking…"
    : `Thought for ${secs < 1 ? "a moment" : secs === 1 ? "1 second" : `${secs} seconds`}`;

  return (
    <div style={{ margin: "4px 0" }}>
      <button
        type="button"
        onClick={() => hasContent && setOpen((p) => !p)}
        style={{
          all: "unset",
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          fontSize: 13,
          color: "var(--muted-foreground, #888)",
          cursor: hasContent ? "pointer" : "default",
          userSelect: "none",
        }}
      >
        <span
          style={{
            display: "inline-block",
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: isStreaming
              ? "var(--primary, #0f6cbd)"
              : "var(--muted-foreground, #888)",
            animation: isStreaming ? "pulse-dot 1.2s infinite" : "none",
          }}
        />
        <span>{label}</span>
        {hasContent && (
          <svg
            width="12"
            height="12"
            viewBox="0 0 16 16"
            fill="currentColor"
            style={{
              transition: "transform 150ms",
              transform: open ? "rotate(90deg)" : "rotate(0deg)",
            }}
          >
            <path
              d="M6 4l4 4-4 4"
              stroke="currentColor"
              strokeWidth="1.5"
              fill="none"
            />
          </svg>
        )}
      </button>
      {open && hasContent && (
        <div
          style={{
            marginTop: 4,
            paddingLeft: 14,
            fontSize: 12,
            lineHeight: 1.5,
            color: "var(--muted-foreground, #888)",
            whiteSpace: "pre-wrap",
            overflowWrap: "break-word",
            borderLeft: "2px solid var(--border, #e0e0e0)",
          }}
        >
          {message.content}
          {isStreaming && (
            <span
              style={{
                display: "inline-block",
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: "var(--muted-foreground, #888)",
                marginLeft: 4,
                verticalAlign: "middle",
                animation: "pulse-dot 1.2s infinite",
              }}
            />
          )}
        </div>
      )}
    </div>
  );
}

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

    if (!msg.parts?.length) {
      result.push({
        id: msg.id,
        role: "assistant",
        content: msg.content,
      } as AGMessage);
      continue;
    }

    let pendingText = "";
    for (const part of msg.parts) {
      if (part.type === "text") {
        pendingText += (pendingText ? "\n\n" : "") + part.content;
      } else if (part.type === "tool_call") {
        const tcId = `${msg.id}-tc-${seq}`;
        const trId = `${msg.id}-tr-${seq}`;
        seq++;

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

        result.push({
          id: trId,
          role: "tool",
          content: part.toolCall.result || "",
          toolCallId: tcId,
        } as AGMessage);
      }
    }

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

function SapChatInner() {
  const { conversationId } = useParams<{ conversationId?: string }>();
  const classes = useStyles();
  const { agent } = useAgent({ agentId: "sap-agent" });

  useDefaultRenderTool();
  useAgentHITL();

  const emittedRef = useRef<string | null>(null);
  useEffect(() => {
    const sub = agent.subscribe({
      onMessagesChanged: ({ messages }) => {
        if (emittedRef.current) return;
        const firstUser = messages.find((m: any) => m.role === "user");
        if (!firstUser) return;
        const threadId = agent.threadId;
        if (!threadId) return;
        if (conversationId === threadId) return;
        emittedRef.current = threadId;
        const preview =
          typeof firstUser.content === "string"
            ? firstUser.content.slice(0, 60)
            : "New chat";
        addOptimisticConversation({
          id: threadId,
          title: preview,
          status: "active",
          workspace_id: "",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          message_count: 1,
        });
      },
    });
    return () => sub.unsubscribe();
  }, [agent, conversationId]);

  useEffect(() => {
    if (!conversationId) return;
    let cancelled = false;
    getConversation(conversationId)
      .then((conv) => {
        if (cancelled) return;
        if (!conv.messages?.length) {
          return;
        }
        const agMsgs = toAgMessages(conv.messages);
        if (agMsgs.length > 0) {
          agent.setMessages(agMsgs);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [conversationId, agent]);

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
        messageView={{
          reasoningMessage: ReasoningMessage as any,
        }}
        labels={{
          modalHeaderTitle: "SAP Assistant",
          welcomeMessageText: "How can I help you with your SAP systems today?",
          chatInputPlaceholder: "Ask about SAP systems...",
        }}
      />
    </div>
  );
}

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
