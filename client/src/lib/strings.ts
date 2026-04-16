// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Application-wide UI strings.
 *
 * Centralises every user-facing label so they can be reviewed, translated,
 * or customised in one place.
 */
export const strings = {
  app: {
    name: "SAP Automation QA",
  },
  auth: {
    initializingAuth: "Initializing authentication…",
    signIn: "Sign in",
    signOut: "Sign out",
    signingIn: "Signing in…",
  },
  chat: {
    inputPlaceholder: "Ask about your SAP systems…",
    modalTitle: "SAP Agent Chat",
    newConversation: "New conversation",
    thinking: "Thinking…",
    thoughtPrefix: "Thought: ",
    thoughtMoment: "Thinking for a moment…",
    welcomeMessage:
      "Hello! I'm the SAP Automation QA agent. How can I help you today?",
  },
  nav: {
    agentDevUi: "Agent DevUI",
    chats: "Chats",
    jobs: "Jobs",
    loadMore: "Load more",
    newChat: "New chat",
    noConversations: "No conversations yet",
    schedules: "Schedules",
    serviceStatus: "Service Status",
    workspaces: "Workspaces",
  },
  pages: {
    dashboard: {
      title: "Dashboard",
      recentJobs: "Recent Jobs",
      noJobs: "No jobs yet.",
    },
    jobDetail: {
      notFound: "Job not found.",
      fields: {
        workspace: "Workspace",
        playbook: "Playbook",
        created: "Created",
        started: "Started",
        completed: "Completed",
        error: "Error",
      },
      cancel: "Cancel",
      cancelling: "Cancelling…",
      loadLog: "Load log",
      refreshLog: "Refresh log",
      refresh: "Refresh",
      emptyLog: "No log output available.",
    },
    jobs: {
      title: "Jobs",
      refresh: "Refresh",
      loadError: "Failed to load jobs.",
      noJobs: "No jobs found.",
      columns: {
        id: "ID",
        workspace: "Workspace",
        playbook: "Playbook",
        status: "Status",
        created: "Created",
      },
    },
    schedules: {
      title: "Schedules",
      refresh: "Refresh",
      loadError: "Failed to load schedules.",
      noSchedules: "No schedules found.",
      active: "Active",
      paused: "Paused",
      delete: "Delete",
      trigger: "Trigger now",
      fields: {
        cron: "Cron expression",
        workspace: "Workspace",
        playbook: "Playbook",
        nextRun: "Next run",
      },
    },
    status: {
      title: "Service Status",
      checking: "Checking…",
      backendUnreachable: "Backend unreachable",
      notReported: "Not reported",
    },
    workspaces: {
      title: "Workspaces",
      refresh: "Refresh",
      loadError: "Failed to load workspaces.",
      noWorkspaces: "No workspaces found.",
      configured: "Configured",
      noConfig: "No configuration",
    },
  },
  shared: {
    loading: "Loading…",
    emptyValue: "—",
    error: "Something went wrong.",
  },
  theme: {
    switchToDark: "Switch to dark theme",
    switchToLight: "Switch to light theme",
  },
  version: {
    updateAvailable: "Update available",
  },
};
