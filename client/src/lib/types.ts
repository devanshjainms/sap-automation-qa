// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/* Shared TypeScript types mirroring backend Pydantic models. */

export interface HealthComponent {
  status: "healthy" | "unhealthy" | "unconfigured";
  latency_ms?: number;
  detail?: string;
}

export interface HealthResponse {
  status: string;
  timestamp?: string;
  version?: string;
  services?: Record<string, boolean>;
  components: Record<string, HealthComponent>;
}

export type JobStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export interface Job {
  id: string;
  workspace_id: string;
  status: JobStatus;
  playbook: string;
  extra_vars: Record<string, string>;
  schedule_id?: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  error?: string;
}

export interface Schedule {
  id: string;
  workspace_id: string;
  name: string;
  cron_expression: string;
  playbook: string;
  extra_vars: Record<string, string>;
  enabled: boolean;
  next_run_time?: string;
  last_run_time?: string;
  created_at: string;
}

export interface Workspace {
  id: string;
  name: string;
  environment: string;
  path: string;
  config_exists: boolean;
}

export interface WorkspaceConfig {
  sap_sid: string;
  db_sid: string;
  platform: string;
  db_instance_number: string;
  scs_instance_number: string;
  ers_instance_number: string;
  database_high_availability: boolean;
  scs_high_availability: boolean;
  database_cluster_type: string;
  scs_cluster_type: string;
  database_scale_out: boolean;
  nfs_provider: string;
  hosts: string[];
}

export interface TestReport {
  filename: string;
  modified_at: string;
  size_bytes: number;
}

export interface Conversation {
  id: string;
  workspace_id: string;
  status: "active" | "archived";
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface ToolCall {
  name: string;
  args: string;
  result: string;
}

export type MessagePart =
  | { type: "text"; content: string }
  | { type: "tool_call"; toolCall: ToolCall };

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  toolCalls?: ToolCall[];
  parts?: MessagePart[];
}
