// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Button,
  Input,
  Spinner,
  Text,
  Tooltip,
  Card,
  mergeClasses,
} from "@fluentui/react-components";
import {
  Send24Regular,
  Wrench16Regular,
} from "@fluentui/react-icons";
import { v4 as uuidv4 } from "uuid";
import ReactMarkdown from "react-markdown";
import {
  createConversation,
  getConversation,
  streamAgUI,
} from "../lib/api";
import type { Message, MessagePart, ToolCall, ToolMeta } from "../lib/types";
import { useStyles } from "../styles/chatPage.styles";

type ToolMetaMap = Record<string, ToolMeta>;

function getToolIcon(name: string, toolMap: ToolMetaMap) {
  const meta = toolMap[name];
  if (meta?.icons?.[0]?.src) {
    return <img src={meta.icons[0].src} alt="" width={16} height={16} />;
  }
  return <Wrench16Regular />;
}

function getToolTitle(name: string, toolMap: ToolMetaMap): string {
  return toolMap[name]?.title || name;
}

function getToolLabel(tc: ToolCall, toolMap: ToolMetaMap): string {
  if (tc.name === "run_evidence_collector") {
    try {
      const a = JSON.parse(tc.args);
      if (a.definition_id) return a.definition_id;
    } catch {}
  }
  return getToolTitle(tc.name, toolMap);
}

/** Renders a single tool call as a compact pill — click to expand result. */
function InlineToolCall({ tc, classes, toolMap }: {
  tc: ToolCall;
  classes: ReturnType<typeof useStyles>;
  toolMap: ToolMetaMap;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <span className={classes.inlineToolCall} onClick={() => setOpen(!open)}>
        <span className={classes.toolCallRowIcon}>{getToolIcon(tc.name, toolMap)}</span>
        <span className={classes.toolCallRowLabel}>{getToolLabel(tc, toolMap)}</span>
      </span>
      {open && tc.result && (
        <pre className={classes.toolCallOutput}>{tc.result}</pre>
      )}
    </div>
  );
}

/** Render an ordered list of message parts (text + tool calls interleaved). */
function MessageParts({ parts, classes, toolMap }: {
  parts: MessagePart[];
  classes: ReturnType<typeof useStyles>;
  toolMap: ToolMetaMap;
}) {
  return (
    <>
      {parts.map((part, i) => {
        if (part.type === "text" && part.content) {
          return (
            <div key={i} className={classes.partText}>
              <ReactMarkdown>{part.content}</ReactMarkdown>
            </div>
          );
        }
        if (part.type === "tool_call") {
          return <InlineToolCall key={i} tc={part.toolCall} classes={classes} toolMap={toolMap} />;
        }
        return null;
      })}
    </>
  );
}

/** Live tool call shown during streaming with a spinner. */
function LiveToolCall({ tc, active, classes, toolMap }: {
  tc: ToolCall;
  active: boolean;
  classes: ReturnType<typeof useStyles>;
  toolMap: ToolMetaMap;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <span className={classes.inlineToolCall} onClick={() => setOpen(!open)}>
        {active && <Spinner size="tiny" />}
        <span className={classes.toolCallRowIcon}>{getToolIcon(tc.name, toolMap)}</span>
        <span className={classes.toolCallRowLabel}>{getToolLabel(tc, toolMap)}</span>
      </span>
      {open && tc.result && (
        <pre className={classes.toolCallOutput}>{tc.result}</pre>
      )}
    </div>
  );
}

const SUGGESTIONS = [
  "Run HA configuration check on HANA cluster",
  "Show recent test failures",
  "What is the status of my SAP landscape?",
  "Schedule a daily DB failover test",
];

export default function ChatPage() {
  const { conversationId: paramId } = useParams<{
    conversationId: string;
  }>();

  const [conversationId, setConversationId] = useState<string | null>(
    paramId ?? null,
  );
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [activity, setActivity] = useState("");
  const [liveParts, setLiveParts] = useState<MessagePart[]>([]);
  const [activeToolIdx, setActiveToolIdx] = useState(-1);
  const [toolMap, setToolMap] = useState<ToolMetaMap>({});
  const bottomRef = useRef<HTMLDivElement>(null);
  const classes = useStyles();

  useEffect(() => {
    if (!paramId) {
      setConversationId(null);
      setMessages([]);
      return;
    }
    setConversationId(paramId);
    getConversation(paramId)
      .then((c) => {
        if (c.messages) setMessages(c.messages);
        if ((c as any).tools) {
          const map: ToolMetaMap = {};
          for (const t of (c as any).tools as ToolMeta[]) {
            map[t.name] = t;
          }
          setToolMap(map);
        }
      })
      .catch(() => {});
  }, [paramId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const ensureConversation = useCallback(async () => {
    if (conversationId) return conversationId;
    const conv = await createConversation();
    setConversationId(conv.id);
    return conv.id;
  }, [conversationId]);

  const sendText = useCallback(
    async (text: string) => {
      if (!text.trim() || streaming) return;

      setInput("");
      const userMsg: Message = {
        id: uuidv4(),
        role: "user",
        content: text.trim(),
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMsg]);

      setStreaming(true);
      setThinking(true);
      setLiveParts([]);
      setActiveToolIdx(-1);
      try {
        const convId = await ensureConversation();

        const assistantMsg: Message = {
          id: uuidv4(),
          role: "assistant",
          content: "",
          timestamp: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, assistantMsg]);

        // Send only the new user message — server-side
        // ConversationHistoryProvider loads full history (with tool
        // calls) from the store.  Sending the full conversation here
        // would duplicate messages and create text-only copies that
        // teach the model to skip tool calls.
        const agMessages = [{ id: userMsg.id, role: "user", content: text.trim() }];

        let currentToolName = "";
        let currentToolArgs = "";
        const collectedParts: MessagePart[] = [];

        for await (const evt of streamAgUI(convId, agMessages)) {
          const t = evt.type as string;

          if (t === "TOOL_CALL_START") {
            setThinking(true);
            currentToolName = (evt.toolCallName as string) || (evt.tool_call_name as string) || "";
            currentToolArgs = "";
            setActivity(currentToolName + "…");
          } else if (t === "TOOL_CALL_ARGS") {
            currentToolArgs += (evt.delta as string) || "";
          } else if (t === "TOOL_CALL_END") {
            const tc: ToolCall = {
              name: currentToolName,
              args: currentToolArgs,
              result: "",
            };
            collectedParts.push({ type: "tool_call", toolCall: tc });
            setLiveParts([...collectedParts]);
            setActiveToolIdx(collectedParts.length - 1);
            setActivity("");
          } else if (t === "TOOL_CALL_RESULT") {
            const result = (evt.content as string) || "";
            if (result) {
              // Find last tool_call part and fill its result.
              for (let i = collectedParts.length - 1; i >= 0; i--) {
                const p = collectedParts[i];
                if (p.type === "tool_call" && !p.toolCall.result) {
                  p.toolCall.result = result.length > 500 ? result.slice(0, 500) + "…" : result;
                  break;
                }
              }
              setLiveParts([...collectedParts]);
              setActiveToolIdx(-1);
              // LLM is now processing the result — show working indicator
              setThinking(true);
              setActivity("Analyzing…");
            }
          } else if (t === "TEXT_MESSAGE_CONTENT" || t === "TEXT_MESSAGE_CHUNK") {
            setThinking(false);
            const chunk = (evt.delta as string) || (evt.content as string) || "";
            if (chunk) {
              // Append to last text part, or create a new one.
              const lastPart = collectedParts[collectedParts.length - 1];
              if (lastPart && lastPart.type === "text") {
                lastPart.content += chunk;
              } else {
                collectedParts.push({ type: "text", content: chunk });
              }
              setLiveParts([...collectedParts]);

              // Also update message content for persistence.
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last.role === "assistant") {
                  updated[updated.length - 1] = {
                    ...last,
                    content: last.content + chunk,
                    parts: [...collectedParts],
                  };
                }
                return updated;
              });
            }
          } else if (t === "RUN_FINISHED") {
            setThinking(false);
            setActivity("");
            setActiveToolIdx(-1);
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last.role === "assistant") {
                const toolCalls = collectedParts
                  .filter((p): p is { type: "tool_call"; toolCall: ToolCall } => p.type === "tool_call")
                  .map((p) => p.toolCall);
                updated[updated.length - 1] = {
                  ...last,
                  parts: [...collectedParts],
                  toolCalls: toolCalls.length > 0 ? toolCalls : last.toolCalls,
                };
              }
              return updated;
            });
          } else if (t === "RUN_ERROR") {
            setThinking(false);
            setActivity("");
            setActiveToolIdx(-1);
            const errorText = (evt.message as string) || "An error occurred";
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last.role === "assistant") {
                updated[updated.length - 1] = {
                  ...last,
                  content: last.content || `Error: ${errorText}`,
                };
              }
              return updated;
            });
          }
        }
      } catch (err) {
        const errMsg: Message = {
          id: uuidv4(),
          role: "assistant",
          content: `Error: ${err instanceof Error ? err.message : String(err)}`,
          timestamp: new Date().toISOString(),
        };
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "assistant" && last.content === "") {
            return [...prev.slice(0, -1), errMsg];
          }
          return [...prev, errMsg];
        });
      } finally {
        setStreaming(false);
        setThinking(false);
        setActivity("");
      }
    },
    [streaming, ensureConversation],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendText(input);
      }
    },
    [sendText, input],
  );

  const showWelcome = messages.length === 0;

  return (
    <div className={classes.page}>
      <div className={classes.chatArea}>
        {showWelcome ? (
          <div className={classes.welcome}>
            <h1 className={classes.heroTitle}>Welcome to SAP Assistant</h1>
            <p className={classes.heroSubtitle}>How can I help you today?</p>
            <div className={classes.suggestions}>
              {SUGGESTIONS.map((s) => (
                <Card
                  key={s}
                  className={mergeClasses(
                    classes.suggestionCard,
                    streaming && classes.suggestionCardDisabled,
                  )}
                  size="small"
                  onClick={() => !streaming && sendText(s)}
                >
                  <Text size={300}>{s}</Text>
                </Card>
              ))}
            </div>
          </div>
        ) : (
          <div className={classes.messages}>
            {messages.map((msg, msgIdx) => (
              <React.Fragment key={msg.id}>
                {msg.role === "user" ? (
                  <div className={classes.userBubble}>
                    <div className={classes.content}>{msg.content}</div>
                  </div>
                ) : (
                  /* While streaming, the last assistant message is rendered
                     by the liveParts block below — skip it here to avoid
                     showing tool calls and text twice. */
                  !(streaming && msgIdx === messages.length - 1) && (
                  <div className={classes.assistantBlock}>
                    {msg.parts && msg.parts.length > 0 ? (
                      <MessageParts parts={msg.parts} classes={classes} toolMap={toolMap} />
                    ) : (
                      msg.content && (
                        <div className={classes.partText}>
                          <ReactMarkdown>{msg.content}</ReactMarkdown>
                        </div>
                      )
                    )}
                  </div>
                  )
                )}
              </React.Fragment>
            ))}
            {streaming && (
              <div className={classes.assistantBlock}>
                {liveParts.map((part, i) => {
                  if (part.type === "text" && part.content) {
                    return (
                      <div key={i} className={classes.partText}>
                        <ReactMarkdown>{part.content}</ReactMarkdown>
                      </div>
                    );
                  }
                  if (part.type === "tool_call") {
                    return (
                      <LiveToolCall
                        key={i}
                        tc={part.toolCall}
                        active={i === activeToolIdx}
                        classes={classes}
                        toolMap={toolMap}
                      />
                    );
                  }
                  return null;
                })}
                {thinking && (
                  <div className={classes.thinkingRow}>
                    <Spinner size="tiny" />
                    <span>{activity || (liveParts.length === 0 ? "Thinking…" : "Working…")}</span>
                  </div>
                )}
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      <div className={classes.inputBar}>
        <div className={classes.inputInner}>
          <Input
            className={classes.input}
            placeholder="Ask about SAP systems..."
            value={input}
            onChange={(_, d) => setInput(d.value)}
            onKeyDown={handleKeyDown}
            disabled={streaming}
            size="large"
          />
          <Tooltip content="Send" relationship="label">
            <Button
              appearance="primary"
              icon={<Send24Regular />}
              onClick={() => sendText(input)}
              disabled={streaming || !input.trim()}
            />
          </Tooltip>
        </div>
      </div>
    </div>
  );
}
