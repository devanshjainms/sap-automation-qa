// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { useCallback, useEffect, useRef, useState } from "react";
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
import { Send24Regular } from "@fluentui/react-icons";
import {
  createConversation,
  getConversation,
  streamMessage,
} from "../lib/api";
import type { Message } from "../lib/types";
import { useStyles } from "../styles/chatPage.styles";

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
      })
      .catch(() => {});
  }, [paramId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const ensureConversation = useCallback(async () => {
    if (conversationId) return conversationId;
    const conv = await createConversation("default");
    setConversationId(conv.id);
    return conv.id;
  }, [conversationId]);

  const sendText = useCallback(
    async (text: string) => {
      if (!text.trim() || streaming) return;

      setInput("");
      const userMsg: Message = {
        id: crypto.randomUUID(),
        role: "user",
        content: text.trim(),
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

        for await (const frame of streamMessage(convId, text.trim())) {
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
                <Spinner
                  size="tiny"
                  label="Thinking..."
                  labelPosition="after"
                />
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
