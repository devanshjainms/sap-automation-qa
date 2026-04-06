// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { CopilotChat } from "@copilotkit/react-core/v2";
import { useStyles } from "../styles/chatPage.styles";

export default function ChatPage() {
  const classes = useStyles();

  return (
    <div className={classes.page}>
      <CopilotChat
        agentId="sap-agent"
        className="copilot-chat-fullpage"
        labels={{
          modalHeaderTitle: "SAP Assistant",
          welcomeMessageText: "How can I help you with your SAP systems today?",
          chatInputPlaceholder: "Ask about SAP systems...",
        }}
      />
    </div>
  );
}
