// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { CopilotSidebar } from "@copilotkit/react-core/v2";

export function CopilotPanel() {
  return (
    <CopilotSidebar
      agentId="sap-agent"
      labels={{
        modalHeaderTitle: "SAP Assistant",
        welcomeMessageText: "Hi! I can help you triage SAP issues, run tests, and manage schedules.",
        chatInputPlaceholder: "Ask about SAP systems...",
      }}
      defaultOpen
    />
  );
}
