// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@copilotkit/react-core/v2/styles.css";
import "./index.css";
import { App } from "./App";
import { AuthProvider, AuthGuard } from "./providers/AuthProvider";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AuthProvider>
      <AuthGuard>
        <App />
      </AuthGuard>
    </AuthProvider>
  </StrictMode>,
);
