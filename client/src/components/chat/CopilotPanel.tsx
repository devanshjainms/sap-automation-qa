// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Button,
  Input,
  Spinner,
  Text,
  Tooltip,
  mergeClasses,
} from "@fluentui/react-components";
import { Send24Regular } from "@fluentui/react-icons";
import { v4 as uuidv4 } from "uuid";
import { createConversation, streamAgUI } from "../../lib/api";
import type { Message } from "../../lib/types";
import { useStyles } from "../../styles/copilotPanel.styles";

export function CopilotPanel() {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [activity, setActivity] = useState("");
  const [activities, setActivities] = useState<string[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);
  const classes = useStyles();

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const ensureConversation = useCallback(async () => {
    if (conversationId) return conversationId;
    const conv = await createConversation();
    setConversationId(conv.id);
    return conv.id;
  }, [conversationId]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;

    setInput("");
    const userMsg: Message = {
      id: uuidv4(),
      role: "user",
      content: text,
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);

    setStreaming(true);
    setThinking(true);
    setActivities([]);
    try {
      const convId = await ensureConversation();
      const assistantMsg: Message = {
        id: uuidv4(),
        role: "assistant",
        content: "",
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
      const collectedActivities: string[] = [];

      // Only send the new message; server loads history with tool calls.
      const agMessages = [{ id: uuidv4(), role: "user", content: text }];

      let currentToolName = "";
      let currentToolArgs = "";

      for await (const evt of streamAgUI(convId, agMessages)) {
        const t = evt.type as string;
        if (t === "TOOL_CALL_START") {
          setThinking(true);
          currentToolName = (evt.toolCallName as string) || "";
          currentToolArgs = "";
          setActivity(currentToolName + "…");
        } else if (t === "TOOL_CALL_ARGS") {
          currentToolArgs += (evt.delta as string) || "";
        } else if (t === "TOOL_CALL_END") {
          let label = currentToolName;
          try {
            const args = JSON.parse(currentToolArgs);
            if (currentToolName === "run_evidence_collector" && args.definition_id) label = args.definition_id;
          } catch {}
          collectedActivities.push(label);
          setActivities([...collectedActivities]);
          setActivity("");
        } else if (t === "TEXT_MESSAGE_CONTENT" || t === "TEXT_MESSAGE_CHUNK") {
          setThinking(false);
          const chunk = (evt.delta as string) || (evt.content as string) || "";
          if (chunk) {
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last.role === "assistant") {
                updated[updated.length - 1] = { ...last, content: last.content + chunk };
              }
              return updated;
            });
          }
        } else if (t === "RUN_FINISHED") {
          setThinking(false);
          setActivity("");
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last.role === "assistant") {
              updated[updated.length - 1] = {
                ...last,
                toolCalls: collectedActivities.length > 0 ? collectedActivities.map((a: string) => ({name: a, args: "", result: ""})) : last.toolCalls,
              };
            }
            return updated;
          });
        } else if (t === "RUN_ERROR") {
          setThinking(false);
          setActivity("");
          const errorText = (evt.message as string) || "An error occurred";
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last.role === "assistant") {
              updated[updated.length - 1] = {
                ...last,
                content: last.content || `Error: ${errorText}`,
                toolCalls: collectedActivities.length > 0 ? collectedActivities.map((a: string) => ({name: a, args: "", result: ""})) : last.toolCalls,
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
  }, [input, streaming, ensureConversation]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  return (
    <div className={classes.panel}>
      <div className={classes.header}>
        <Text weight="semibold" size={400}>
          SAP Assistant
        </Text>
      </div>

      <div className={classes.messages}>
        {messages.length === 0 && (
          <div className={classes.welcome}>
            <Text size={300}>
              Hi! I can help you triage SAP issues, run tests, and manage
              schedules. What would you like to do?
            </Text>
          </div>
        )}
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={
              msg.role === "user"
                ? classes.userBubble
                : classes.assistantBubble
            }
          >
            <Text
              size={200}
              className={mergeClasses(
                classes.role,
                msg.role === "user" && classes.userRole,
              )}
            >
              {msg.role === "user" ? "You" : "Assistant"}
            </Text>
            {msg.role === "assistant" && (msg.toolCalls?.length ?? 0) > 0 && (
              <details className={classes.activitiesDisclosure}>
                <summary className={classes.activitiesSummary}>
                  Used {(msg.toolCalls ?? []).length} tool{(msg.toolCalls ?? []).length !== 1 ? "s" : ""}
                </summary>
                <div className={classes.activitiesList}>
                  {msg.toolCalls!.map((tc, i) => (
                    <div key={i} className={classes.activityItem}>✓ {tc.name}</div>
                  ))}
                </div>
              </details>
            )}
            {msg.content && (
              <div className={classes.content}>{msg.content}</div>
            )}
          </div>
        ))}
        {thinking && (
          <div className={classes.assistantBubble}>
            {activities.length > 0 && (
              <div className={classes.activitiesList}>
                {activities.map((a, i) => (
                  <div key={i} className={classes.activityItem}>✓ {a}</div>
                ))}
              </div>
            )}
            <div className={classes.thinkingRow}>
              <Spinner size="tiny" />
              <span>{activity || "Thinking\u2026"}</span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className={classes.inputRow}>
        <Input
          className={classes.input}
          placeholder="Ask about SAP systems..."
          value={input}
          onChange={(_, d) => setInput(d.value)}
          onKeyDown={handleKeyDown}
          disabled={streaming}
        />
        <Tooltip content="Send" relationship="label">
          <Button
            appearance="primary"
            icon={<Send24Regular />}
            onClick={handleSend}
            disabled={streaming || !input.trim()}
          />
        </Tooltip>
      </div>
    </div>
  );
}
