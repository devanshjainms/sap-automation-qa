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
import { acquireToken } from "../../lib/auth";
import { strings } from "../../lib/strings";
import { AGENT_ID } from "../../lib/constants";
import type { RunAgentInput } from "@ag-ui/client";

/**
 * Module-level token cache. Updated before each agent run
 * via the ``useAgentAuth`` hook below.
 */
let _cachedToken: string | null = null;

/** Call before each agent interaction to refresh the token. */
export async function refreshAgentToken(): Promise<void> {
  _cachedToken = await acquireToken();
}

/**
 * HttpAgent subclass that injects the cached Azure AD Bearer token.
 * ``requestInit`` is synchronous so we read from the module cache
 * which is populated by ``refreshAgentToken()`` in the React hook.
 */
class AuthenticatedHttpAgent extends HttpAgent {
  protected requestInit(input: RunAgentInput): RequestInit {
    const base = super.requestInit(input);
    if (_cachedToken) {
      const headers = new Headers(base.headers);
      headers.set("Authorization", `Bearer ${_cachedToken}`);
      return { ...base, headers };
    }
    return base;
  }
}

const sapAgent = new AuthenticatedHttpAgent({
  url: "/ag-ui",
  agentId: AGENT_ID,
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
  const classes = useStyles();
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
    ? strings.chat.thinking
    : `${strings.chat.thoughtPrefix} ${secs < 1 ? strings.chat.thoughtMoment : secs === 1 ? "1 second" : `${secs} seconds`}`;

  return (
    <div className={classes.reasoningWrapper}>
      <button
        type="button"
        onClick={() => hasContent && setOpen((p) => !p)}
        className={`${classes.reasoningButton} ${hasContent ? classes.reasoningButtonClickable : classes.reasoningButtonDefault}`}
      >
        <span
          className={`${classes.reasoningDot} ${isStreaming ? classes.reasoningDotActive : classes.reasoningDotInactive}`}
        />
        <span>{label}</span>
        {hasContent && (
          <svg
            width="12"
            height="12"
            viewBox="0 0 16 16"
            fill="currentColor"
            className={`${classes.reasoningChevron} ${open ? classes.reasoningChevronOpen : classes.reasoningChevronClosed}`}
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
        <div className={classes.reasoningContent}>
          {message.content}
          {isStreaming && <span className={classes.reasoningStreamDot} />}
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

        // Only emit a tool result when one actually exists.
        // Pending approvals have no result yet — emitting an
        // empty result would mark them as completed on reload.
        if (part.toolCall.result) {
          result.push({
            id: trId,
            role: "tool",
            content: part.toolCall.result,
            toolCallId: tcId,
          } as AGMessage);
        }
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
  const { agent } = useAgent({ agentId: AGENT_ID });

  useDefaultRenderTool();
  useAgentHITL();

  useEffect(() => {
    refreshAgentToken();
    const interval = setInterval(refreshAgentToken, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

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
            : strings.chat.newConversation;
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
        agentId={AGENT_ID}
        threadId={conversationId}
        className="copilot-chat-fullpage"
        messageView={{
          reasoningMessage: ReasoningMessage as any,
        }}
        labels={{
          modalHeaderTitle: strings.chat.modalTitle,
          welcomeMessageText: strings.chat.welcomeMessage,
          chatInputPlaceholder: strings.chat.inputPlaceholder,
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
      agents__unsafe_dev_only={{ [AGENT_ID]: sapAgent }}
      showDevConsole={false}
    >
      <SapChatInner />
    </CopilotKitProvider>
  );
}
