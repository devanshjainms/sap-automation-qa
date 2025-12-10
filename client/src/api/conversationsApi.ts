// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Conversations API Service - Manages conversation CRUD operations.
 */
import { apiClient } from "./client";
import { API_ENDPOINTS, buildConversationsQuery } from "./endpoints";
import {
  ConversationListResponse,
  ConversationDetailResponse,
  Conversation,
} from "../types";

export interface ListConversationsParams {
  limit?: number;
  offset?: number;
  userId?: string;
}

export interface UpdateConversationParams {
  title?: string;
  workspaceId?: string;
  metadata?: Record<string, unknown>;
}

export const conversationsApi = {
  list: async (
    params: ListConversationsParams = {},
  ): Promise<ConversationListResponse> => {
    const query = buildConversationsQuery(params);
    const url = query
      ? `${API_ENDPOINTS.CONVERSATIONS}?${query}`
      : API_ENDPOINTS.CONVERSATIONS;

    const response = await apiClient.get<ConversationListResponse>(url);
    return response.data;
  },

  getById: async (
    conversationId: string,
  ): Promise<ConversationDetailResponse> => {
    const response = await apiClient.get<ConversationDetailResponse>(
      API_ENDPOINTS.CONVERSATION_BY_ID(conversationId),
    );
    return response.data;
  },

  update: async (
    conversationId: string,
    params: UpdateConversationParams,
  ): Promise<{ conversation: Conversation }> => {
    const response = await apiClient.patch<{ conversation: Conversation }>(
      API_ENDPOINTS.CONVERSATION_BY_ID(conversationId),
      params,
    );
    return response.data;
  },

  delete: async (conversationId: string): Promise<void> => {
    await apiClient.delete(API_ENDPOINTS.CONVERSATION_BY_ID(conversationId));
  },
};
