// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Chat API Service - Handles chat message operations.
 */
import { apiClient } from "./client";
import { API_ENDPOINTS, buildChatQuery } from "./endpoints";
import { ChatMessage, ChatResponse } from "../types";

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
      const response = await fetch(`${apiClient.defaults.baseURL}${url}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          messages: params.messages,
          correlation_id: params.correlationId,
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
