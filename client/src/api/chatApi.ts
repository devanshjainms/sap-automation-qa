// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Chat API Service - Handles chat message operations.
 */
import { apiClient, generateUUID } from "./client";
import { API_ENDPOINTS, buildChatQuery } from "./endpoints";
import { ChatMessage, ChatResponse } from "../types";

export interface ThinkingStep {
  id: string;
  agent: string;
  action: string;
  detail?: string;
  status: "pending" | "in_progress" | "complete" | "error";
  duration_ms?: number;
}

export interface StreamCallbacks {
  onThinkingStart?: () => void;
  onThinkingStep?: (step: ThinkingStep) => void;
  onThinkingEnd?: () => void;
  onContent?: (content: string) => void;
  onComplete?: (response: ChatResponse) => void;
  onError?: (error: Error) => void;
}

export interface SendMessageParams {
  messages: ChatMessage[];
  conversationId?: string;
  userId?: string;
  correlationId?: string;
  workspaceIds?: string[];
}

export const chatApi = {
  sendMessage: async (params: SendMessageParams): Promise<ChatResponse> => {
    const query = buildChatQuery({
      conversationId: params.conversationId,
      userId: params.userId,
    });

    const url = query ? `${API_ENDPOINTS.CHAT}?${query}` : API_ENDPOINTS.CHAT;

    const response = await apiClient.post<ChatResponse>(url, {
      messages: params.messages,
      correlation_id: params.correlationId,
      workspace_ids: params.workspaceIds,
    });

    return response.data;
  },

  sendMessageStreamWithThinking: async (
    params: SendMessageParams,
    callbacks: StreamCallbacks,
  ): Promise<void> => {
    const query = buildChatQuery({
      conversationId: params.conversationId,
      userId: params.userId,
    });

    const url = `${API_ENDPOINTS.CHAT}/stream${query ? `?${query}` : ""}`;

    try {
      const correlationId = params.correlationId || generateUUID();
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        "X-Correlation-ID": correlationId,
      };
      if (params.conversationId) {
        headers["X-Conversation-ID"] = params.conversationId;
      }

      const response = await fetch(`${apiClient.defaults.baseURL}${url}`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          messages: params.messages,
          correlation_id: correlationId,
          workspace_ids: params.workspaceIds,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error("No response body");
      }

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        let currentEvent = "";
        for (const line of lines) {
          if (line.startsWith("event: ")) {
            currentEvent = line.slice(7).trim();
          } else if (line.startsWith("data: ")) {
            const data = line.slice(6);
            try {
              const parsed = JSON.parse(data);

              switch (currentEvent) {
                case "thinking_start":
                  callbacks.onThinkingStart?.();
                  break;
                case "thinking_step":
                  if (parsed.step) {
                    callbacks.onThinkingStep?.(parsed.step);
                  }
                  break;
                case "thinking_end":
                  callbacks.onThinkingEnd?.();
                  break;
                case "content":
                  if (parsed.content) {
                    callbacks.onContent?.(parsed.content);
                  }
                  break;
                case "done":
                  const chatResponse: ChatResponse = {
                    messages: [],
                    test_plan: null,
                    correlation_id: parsed.correlation_id || correlationId,
                    reasoning_trace: parsed.reasoning_trace || null,
                    metadata: {
                      conversation_id: parsed.conversation_id,
                    },
                  };
                  callbacks.onComplete?.(chatResponse);
                  break;
                case "error":
                  callbacks.onError?.(new Error(parsed.message || "Unknown error"));
                  break;
              }
            } catch {
              // Partial JSON, continue
            }
            currentEvent = "";
          }
        }
      }
    } catch (error) {
      callbacks.onError?.(error instanceof Error ? error : new Error("Stream error"));
    }
  },

  sendMessageStream: async (
    params: SendMessageParams,
    onChunk: (chunk: string) => void,
    onComplete: (response: ChatResponse) => void,
    onError: (error: Error) => void,
  ): Promise<void> => {
    const query = buildChatQuery({
      conversationId: params.conversationId,
      userId: params.userId,
    });

    const url = `${API_ENDPOINTS.CHAT}/stream${query ? `?${query}` : ""}`;

    try {
      const correlationId = params.correlationId || generateUUID();
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        "X-Correlation-ID": correlationId,
      };
      if (params.conversationId) {
        headers["X-Conversation-ID"] = params.conversationId;
      }

      const response = await fetch(`${apiClient.defaults.baseURL}${url}`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          messages: params.messages,
          correlation_id: correlationId,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error("No response body");
      }

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const data = line.slice(6);
            if (data === "[DONE]") {
              continue;
            }
            try {
              const parsed = JSON.parse(data);
              if (parsed.content) {
                onChunk(parsed.content);
              }
              if (parsed.complete) {
                onComplete(parsed.response);
              }
            } catch {
              // Partial JSON, continue buffering
            }
          }
        }
      }
    } catch (error) {
      onError(error instanceof Error ? error : new Error("Stream error"));
    }
  },
};
