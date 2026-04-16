// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@copilotkit/react-core/v2/styles.css";
import "./index.css";
import { App } from "./App";
import { ErrorBoundary } from "./components/shared/ErrorBoundary";
import { AuthProvider, AuthGuard } from "./providers/AuthProvider";
import { ThemeProvider } from "./hooks/useTheme";
import { DarkModeSync } from "./components/DarkModeSync";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <DarkModeSync />
      <ErrorBoundary>
        <AuthProvider>
          <AuthGuard>
            <App />
          </AuthGuard>
        </AuthProvider>
      </ErrorBoundary>
    </ThemeProvider>
  </StrictMode>,
);
