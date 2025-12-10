// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Chat Context
 * Global state management for chat functionality using React Context and useReducer.
 */

import React, {
  createContext,
  useContext,
  useReducer,
  useCallback,
  ReactNode,
} from "react";
import {
  ChatMessage,
  ConversationListItem,
  Message,
  ReasoningTrace,
  TestPlan,
} from "../types";
import { chatApi, conversationsApi } from "../api";
import { APP_CONFIG } from "../constants";

interface ChatState {
  conversationId: string | null;
  messages: ChatMessage[];
  isLoading: boolean;
  isStreaming: boolean;
  error: string | null;
  conversations: ConversationListItem[];
  conversationsLoading: boolean;
  reasoningTrace: ReasoningTrace | null;
  testPlan: TestPlan | null;
  selectedWorkspaceId: string | null;
}

type ChatAction =
  | { type: "SET_CONVERSATION_ID"; payload: string | null }
  | { type: "SET_MESSAGES"; payload: ChatMessage[] }
  | { type: "ADD_MESSAGE"; payload: ChatMessage }
  | { type: "UPDATE_LAST_MESSAGE"; payload: string }
  | { type: "SET_LOADING"; payload: boolean }
  | { type: "SET_STREAMING"; payload: boolean }
  | { type: "SET_ERROR"; payload: string | null }
  | { type: "SET_CONVERSATIONS"; payload: ConversationListItem[] }
  | { type: "SET_CONVERSATIONS_LOADING"; payload: boolean }
  | { type: "ADD_CONVERSATION"; payload: ConversationListItem }
  | { type: "UPDATE_CONVERSATION"; payload: { id: string; title: string } }
  | { type: "REMOVE_CONVERSATION"; payload: string }
  | { type: "SET_REASONING_TRACE"; payload: ReasoningTrace | null }
  | { type: "SET_TEST_PLAN"; payload: TestPlan | null }
  | { type: "SET_SELECTED_WORKSPACE"; payload: string | null }
  | { type: "RESET_CHAT" };

const initialState: ChatState = {
  conversationId: null,
  messages: [],
  isLoading: false,
  isStreaming: false,
  error: null,
  conversations: [],
  conversationsLoading: false,
  reasoningTrace: null,
  testPlan: null,
  selectedWorkspaceId: localStorage.getItem(
    APP_CONFIG.STORAGE_KEYS.SELECTED_WORKSPACE,
  ),
};

const chatReducer = (state: ChatState, action: ChatAction): ChatState => {
  switch (action.type) {
    case "SET_CONVERSATION_ID":
      return { ...state, conversationId: action.payload };
    case "SET_MESSAGES":
      return { ...state, messages: action.payload };
    case "ADD_MESSAGE":
      return { ...state, messages: [...state.messages, action.payload] };
    case "UPDATE_LAST_MESSAGE":
      const updatedMessages = [...state.messages];
      if (updatedMessages.length > 0) {
        updatedMessages[updatedMessages.length - 1] = {
          ...updatedMessages[updatedMessages.length - 1],
          content: action.payload,
        };
      }
      return { ...state, messages: updatedMessages };
    case "SET_LOADING":
      return { ...state, isLoading: action.payload };
    case "SET_STREAMING":
      return { ...state, isStreaming: action.payload };
    case "SET_ERROR":
      return { ...state, error: action.payload };
    case "SET_CONVERSATIONS":
      return { ...state, conversations: action.payload };
    case "SET_CONVERSATIONS_LOADING":
      return { ...state, conversationsLoading: action.payload };
    case "ADD_CONVERSATION":
      return {
        ...state,
        conversations: [action.payload, ...state.conversations],
      };
    case "UPDATE_CONVERSATION":
      return {
        ...state,
        conversations: state.conversations.map((c) =>
          c.id === action.payload.id
            ? { ...c, title: action.payload.title }
            : c,
        ),
      };
    case "REMOVE_CONVERSATION":
      return {
        ...state,
        conversations: state.conversations.filter(
          (c) => c.id !== action.payload,
        ),
      };
    case "SET_REASONING_TRACE":
      return { ...state, reasoningTrace: action.payload };
    case "SET_TEST_PLAN":
      return { ...state, testPlan: action.payload };
    case "SET_SELECTED_WORKSPACE":
      if (action.payload) {
        localStorage.setItem(
          APP_CONFIG.STORAGE_KEYS.SELECTED_WORKSPACE,
          action.payload,
        );
      } else {
        localStorage.removeItem(APP_CONFIG.STORAGE_KEYS.SELECTED_WORKSPACE);
      }
      return { ...state, selectedWorkspaceId: action.payload };
    case "RESET_CHAT":
      return {
        ...state,
        conversationId: null,
        messages: [],
        error: null,
        reasoningTrace: null,
        testPlan: null,
      };
    default:
      return state;
  }
};

interface ChatContextType {
  state: ChatState;
  sendMessage: (content: string, workspaceIds?: string[]) => Promise<void>;
  loadConversation: (conversationId: string) => Promise<void>;
  loadConversations: () => Promise<void>;
  startNewChat: () => void;
  deleteConversation: (conversationId: string) => Promise<void>;
  renameConversation: (conversationId: string, title: string) => Promise<void>;
  setSelectedWorkspace: (workspaceId: string | null) => void;
  clearError: () => void;
}

const ChatContext = createContext<ChatContextType | undefined>(undefined);

export const ChatProvider: React.FC<{ children: ReactNode }> = ({
  children,
}) => {
  const [state, dispatch] = useReducer(chatReducer, initialState);

  const sendMessage = useCallback(
    async (content: string, workspaceIds?: string[]) => {
      if (!content.trim()) return;

      const userMessage: ChatMessage = {
        role: "user",
        content: content.trim(),
      };
      dispatch({ type: "ADD_MESSAGE", payload: userMessage });
      dispatch({ type: "SET_LOADING", payload: true });
      dispatch({ type: "SET_ERROR", payload: null });

      try {
        let messagesWithContext: ChatMessage[] = [
          ...state.messages,
          userMessage,
        ];

        const hasWorkspaces = workspaceIds && workspaceIds.length > 0;
        if (hasWorkspaces && state.messages.length === 0) {
          messagesWithContext = [
            {
              role: "system",
              content: `User has selected workspace(s): ${workspaceIds.join(", ")}. Use these as the default context for any operations.`,
            },
            userMessage,
          ];
        }

        const response = await chatApi.sendMessage({
          messages: messagesWithContext,
          conversationId: state.conversationId || undefined,
          workspaceIds: workspaceIds,
        });

        if (response.metadata?.conversation_id && !state.conversationId) {
          dispatch({
            type: "SET_CONVERSATION_ID",
            payload: response.metadata.conversation_id,
          });

          dispatch({ type: "SET_CONVERSATIONS_LOADING", payload: true });
          conversationsApi
            .list({ limit: 50 })
            .then((res) => {
              dispatch({
                type: "SET_CONVERSATIONS",
                payload: res.conversations,
              });
              dispatch({ type: "SET_CONVERSATIONS_LOADING", payload: false });
            })
            .catch(() => {
              dispatch({ type: "SET_CONVERSATIONS_LOADING", payload: false });
            });
        }

        if (response.messages.length > 0) {
          const assistantMessage =
            response.messages[response.messages.length - 1];
          dispatch({ type: "ADD_MESSAGE", payload: assistantMessage });
        }

        dispatch({
          type: "SET_REASONING_TRACE",
          payload: response.reasoning_trace,
        });
        dispatch({ type: "SET_TEST_PLAN", payload: response.test_plan });
      } catch (error) {
        console.error("Failed to send message:", error);
        dispatch({
          type: "SET_ERROR",
          payload:
            error instanceof Error ? error.message : "Failed to send message",
        });
      } finally {
        dispatch({ type: "SET_LOADING", payload: false });
      }
    },
    [state.conversationId, state.messages],
  );

  const loadConversation = useCallback(async (conversationId: string) => {
    dispatch({ type: "SET_LOADING", payload: true });
    dispatch({ type: "SET_ERROR", payload: null });

    try {
      const response = await conversationsApi.getById(conversationId);

      const chatMessages: ChatMessage[] = response.messages.map(
        (m: Message) => ({
          role: m.role,
          content: m.content,
        }),
      );

      dispatch({ type: "SET_CONVERSATION_ID", payload: conversationId });
      dispatch({ type: "SET_MESSAGES", payload: chatMessages });
      dispatch({ type: "SET_REASONING_TRACE", payload: null });
      dispatch({ type: "SET_TEST_PLAN", payload: null });

      if (response.conversation.active_workspace_id) {
        dispatch({
          type: "SET_SELECTED_WORKSPACE",
          payload: response.conversation.active_workspace_id,
        });
      }
    } catch (error) {
      console.error("Failed to load conversation:", error);
      dispatch({
        type: "SET_ERROR",
        payload:
          error instanceof Error
            ? error.message
            : "Failed to load conversation",
      });
    } finally {
      dispatch({ type: "SET_LOADING", payload: false });
    }
  }, []);

  const loadConversations = useCallback(async () => {
    dispatch({ type: "SET_CONVERSATIONS_LOADING", payload: true });

    try {
      const response = await conversationsApi.list({ limit: 50 });
      dispatch({ type: "SET_CONVERSATIONS", payload: response.conversations });
    } catch (error) {
      console.error("Failed to load conversations:", error);
    } finally {
      dispatch({ type: "SET_CONVERSATIONS_LOADING", payload: false });
    }
  }, []);

  const startNewChat = useCallback(() => {
    dispatch({ type: "RESET_CHAT" });
  }, []);

  const deleteConversation = useCallback(
    async (conversationId: string) => {
      try {
        await conversationsApi.delete(conversationId);
        dispatch({ type: "REMOVE_CONVERSATION", payload: conversationId });

        if (state.conversationId === conversationId) {
          dispatch({ type: "RESET_CHAT" });
        }
      } catch (error) {
        console.error("Failed to delete conversation:", error);
        throw error;
      }
    },
    [state.conversationId],
  );

  const renameConversation = useCallback(
    async (conversationId: string, title: string) => {
      try {
        await conversationsApi.update(conversationId, { title });
        dispatch({
          type: "UPDATE_CONVERSATION",
          payload: { id: conversationId, title },
        });
      } catch (error) {
        console.error("Failed to rename conversation:", error);
        throw error;
      }
    },
    [],
  );

  const setSelectedWorkspace = useCallback((workspaceId: string | null) => {
    dispatch({ type: "SET_SELECTED_WORKSPACE", payload: workspaceId });
  }, []);

  const clearError = useCallback(() => {
    dispatch({ type: "SET_ERROR", payload: null });
  }, []);

  const value: ChatContextType = {
    state,
    sendMessage,
    loadConversation,
    loadConversations,
    startNewChat,
    deleteConversation,
    renameConversation,
    setSelectedWorkspace,
    clearError,
  };

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
};

export const useChat = (): ChatContextType => {
  const context = useContext(ChatContext);
  if (!context) {
    throw new Error("useChat must be used within a ChatProvider");
  }
  return context;
};
