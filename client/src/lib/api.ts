// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/* Typed wrappers for the SAP QA REST API. */

import type {
  Conversation,
  HealthResponse,
  Job,
  Message,
  Schedule,
  Workspace,
} from "./types";

const BASE = "/api/v1";

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

/* ── Health ─────────────────────────────────────────────────── */

export function getHealth(): Promise<HealthResponse> {
  return fetchJson<HealthResponse>("/healthz");
}

/* ── Jobs ──────────────────────────────────────────────────── */

export async function listJobs(params?: {
  workspace_id?: string;
  status?: string;
}): Promise<Job[]> {
  const qs = new URLSearchParams();
  if (params?.workspace_id) qs.set("workspace_id", params.workspace_id);
  if (params?.status) qs.set("status", params.status);
  const suffix = qs.toString() ? `?${qs}` : "";
  const res = await fetchJson<{ jobs: Job[]; total: number } | Job[]>(
    `${BASE}/jobs${suffix}`,
  );
  return Array.isArray(res) ? res : res.jobs;
}

export function getJob(id: string): Promise<Job> {
  return fetchJson<Job>(`${BASE}/jobs/${encodeURIComponent(id)}`);
}

export function cancelJob(id: string): Promise<void> {
  return fetchJson(`${BASE}/jobs/${encodeURIComponent(id)}/cancel`, {
    method: "POST",
  });
}

export function getJobLog(
  id: string,
  tail?: number,
): Promise<string> {
  const qs = tail ? `?tail=${tail}` : "";
  return fetch(
    `${BASE}/jobs/${encodeURIComponent(id)}/log${qs}`,
  ).then((r) => r.text());
}

/* ── Schedules ─────────────────────────────────────────────── */

export async function listSchedules(): Promise<Schedule[]> {
  const res = await fetchJson<{ schedules: Schedule[]; total: number } | Schedule[]>(
    `${BASE}/schedules`,
  );
  return Array.isArray(res) ? res : res.schedules;
}

export function createSchedule(body: {
  workspace_id: string;
  name: string;
  cron_expression: string;
  playbook: string;
  extra_vars?: Record<string, string>;
}): Promise<Schedule> {
  return fetchJson<Schedule>(`${BASE}/schedules`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteSchedule(id: string): Promise<void> {
  return fetchJson(`${BASE}/schedules/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export function triggerSchedule(id: string): Promise<void> {
  return fetchJson(
    `${BASE}/schedules/${encodeURIComponent(id)}/trigger`,
    { method: "POST" },
  );
}

/* ── Workspaces ────────────────────────────────────────────── */

export async function listWorkspaces(): Promise<Workspace[]> {
  const res = await fetchJson<{ workspaces: Workspace[]; total: number } | Workspace[]>(
    `${BASE}/workspaces`,
  );
  return Array.isArray(res) ? res : res.workspaces;
}

/* ── Chat ──────────────────────────────────────────────────── */

export function createConversation(workspaceId: string): Promise<Conversation> {
  return fetchJson<Conversation>(`${BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ workspace_id: workspaceId }),
  });
}

export function listConversations(workspaceId?: string): Promise<Conversation[]> {
  const qs = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "";
  return fetchJson<Conversation[]>(`${BASE}/chat${qs}`);
}

export function getConversation(id: string): Promise<Conversation & { messages: Message[] }> {
  return fetchJson(`${BASE}/chat/${encodeURIComponent(id)}`);
}

export function sendMessage(conversationId: string, content: string): Promise<Message> {
  return fetchJson<Message>(
    `${BASE}/chat/${encodeURIComponent(conversationId)}/messages`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    },
  );
}

/**
 * Stream an assistant response via SSE.
 * Yields `{ event, data }` objects for each SSE frame.
 */
export async function* streamMessage(
  conversationId: string,
  content: string,
): AsyncGenerator<{ event: string; data: string }> {
  const res = await fetch(
    `${BASE}/chat/${encodeURIComponent(conversationId)}/messages/stream`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    },
  );
  if (!res.ok || !res.body) {
    throw new Error(`${res.status}: ${await res.text().catch(() => res.statusText)}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let currentEvent = "message";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (line.startsWith("event: ")) {
        currentEvent = line.slice(7).trim();
      } else if (line.startsWith("data: ")) {
        yield { event: currentEvent, data: line.slice(6) };
        currentEvent = "message";
      }
    }
  }
}
