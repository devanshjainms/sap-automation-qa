// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Type Definitions
 * TypeScript interfaces and types for the application.
 */

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

export interface ReasoningStep {
  id: string;
  agent: string;
  phase: string;
  kind: "routing" | "tool_call" | "inference" | "decision" | "error";
  description: string;
  input_snapshot: Record<string, unknown>;
  output_snapshot: Record<string, unknown>;
  timestamp: string;
  error: string | null;
}

export interface ReasoningTrace {
  trace_id: string;
  steps: ReasoningStep[];
  created_at: string;
  agent_name: string;
}

export interface TestPlanItem {
  test_id: string;
  test_name: string;
  test_group: string;
  description: string;
  is_destructive: boolean;
  workspace_id?: string;
}

export interface TestPlan {
  items: TestPlanItem[];
  workspace_id: string;
  estimated_duration?: string;
}

export interface ChatResponse {
  messages: ChatMessage[];
  test_plan: TestPlan | null;
  correlation_id: string;
  reasoning_trace: ReasoningTrace | null;
  metadata: {
    conversation_id: string;
    [key: string]: unknown;
  } | null;
}

export interface ConversationListItem {
  id: string;
  title: string;
  updated_at: string;
}

export interface Conversation {
  id: string;
  user_id: string | null;
  title: string;
  created_at: string;
  updated_at: string;
  active_workspace_id: string | null;
  metadata: Record<string, unknown>;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
  metadata: Record<string, unknown>;
}

export interface ConversationWithMessages {
  conversation: Conversation;
  messages: Message[];
}

export interface Workspace {
  workspace_id: string;
  env?: string;
  region?: string;
  deployment_code?: string;
  sid?: string;
  sap_sid?: string;
  environment?: string;
  capabilities?: WorkspaceCapabilities;
}

export interface WorkspaceCapabilities {
  system_role: string;
  hana: boolean;
  database_platform: string;
  database_high_availability: boolean;
  database_cluster_type: string;
  scs_high_availability: boolean;
  scs_cluster_type: string;
  ascs_ers: boolean;
  ha_cluster: boolean;
  nfs_provider: string;
  sap_sid: string;
  db_sid: string;
  db_instance_number: string;
  scs_instance_number: string;
  ers_instance_number: string;
}

export type JobStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export interface Job {
  job_id: string;
  conversation_id: string;
  status: JobStatus;
  test_id: string;
  workspace_id: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  result?: unknown;
  error?: string;
}

export interface ConversationListResponse {
  conversations: ConversationListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface ConversationDetailResponse {
  conversation: Conversation;
  messages: Message[];
}

export interface HealthResponse {
  status: "healthy" | "unhealthy";
}
