// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { BrowserRouter, Routes, Route } from "react-router-dom";
import { ThemeProvider } from "./hooks/useTheme";
import { AppShell } from "./components/layout/AppShell";
import ChatPage from "./pages/ChatPage";
import { Dashboard } from "./pages/Dashboard";
import { Jobs } from "./pages/Jobs";
import { JobDetailPage } from "./pages/JobDetailPage";
import { Schedules } from "./pages/Schedules";
import { Workspaces } from "./pages/Workspaces";

export function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<ChatPage />} />
            <Route path="chat/:conversationId" element={<ChatPage />} />
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="jobs" element={<Jobs />} />
            <Route path="jobs/:id" element={<JobDetailPage />} />
            <Route path="schedules" element={<Schedules />} />
            <Route path="workspaces" element={<Workspaces />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  );
}
