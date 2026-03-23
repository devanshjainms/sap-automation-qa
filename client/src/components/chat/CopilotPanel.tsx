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
import { createConversation, streamMessage } from "../../lib/api";
import type { Message } from "../../lib/types";
import { useStyles } from "../../styles/copilotPanel.styles";

export function CopilotPanel() {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const classes = useStyles();

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const ensureConversation = useCallback(async () => {
    if (conversationId) return conversationId;
    const conv = await createConversation("default");
    setConversationId(conv.id);
    return conv.id;
  }, [conversationId]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;

    setInput("");
    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);

    setStreaming(true);
    try {
      const convId = await ensureConversation();
      const assistantMsg: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: "",
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, assistantMsg]);

      for await (const frame of streamMessage(convId, text)) {
        if (frame.event === "token") {
          const parsed = JSON.parse(frame.data);
          const token = parsed.token ?? parsed.content ?? frame.data;
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last.role === "assistant") {
              updated[updated.length - 1] = {
                ...last,
                content: last.content + token,
              };
            }
            return updated;
          });
        }
      }
    } catch (err) {
      const errMsg: Message = {
        id: crypto.randomUUID(),
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
            <div className={classes.content}>{msg.content}</div>
          </div>
        ))}
        {streaming && (
          <div className={classes.spinnerRow}>
            <Spinner size="tiny" label="Thinking..." labelPosition="after" />
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
