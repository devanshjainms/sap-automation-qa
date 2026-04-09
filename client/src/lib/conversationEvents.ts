// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Lightweight pub/sub for sidebar ↔ chat communication.
 *
 * When a new conversation is created (or its title updates),
 * the chat component emits an event and the sidebar picks it
 * up immediately — no polling required.
 */

import type { Conversation } from "./types";

type Listener = () => void;

const listeners = new Set<Listener>();

/** Optimistic entries keyed by conversationId. */
const optimistic = new Map<string, Conversation>();

/** Subscribe to conversation list changes. Returns unsubscribe fn. */
export function onConversationsChanged(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Notify all listeners that the conversation list changed. */
function notify() {
  listeners.forEach((fn) => fn());
}

/**
 * Add an optimistic conversation entry (shown instantly in sidebar).
 * Deduplicates by id — calling again with same id updates the entry.
 */
export function addOptimisticConversation(conv: Conversation): void {
  optimistic.set(conv.id, conv);
  notify();
}

/** Update the title of an optimistic entry. */
export function updateOptimisticTitle(id: string, title: string): void {
  const existing = optimistic.get(id);
  if (existing) {
    optimistic.set(id, { ...existing, title });
    notify();
  }
}

/** Remove an optimistic entry (e.g. after server data includes it). */
export function removeOptimistic(id: string): void {
  if (optimistic.delete(id)) notify();
}

/** Get all current optimistic entries. */
export function getOptimisticConversations(): Conversation[] {
  return Array.from(optimistic.values());
}
