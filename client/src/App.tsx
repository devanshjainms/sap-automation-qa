// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { BrowserRouter, Routes, Route } from "react-router-dom";
import { ThemeProvider } from "./hooks/useTheme";
import { DarkModeSync } from "./components/DarkModeSync";
import { AppShell } from "./components/layout/AppShell";
import ChatPage from "./pages/ChatPage";
import { Dashboard } from "./pages/Dashboard";
import { Jobs } from "./pages/Jobs";
import { JobDetailPage } from "./pages/JobDetailPage";
import { Schedules } from "./pages/Schedules";
import { Workspaces } from "./pages/Workspaces";
import { Status } from "./pages/Status";

export function App() {
  return (
    <ThemeProvider>
      <DarkModeSync />
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
            <Route path="status" element={<Status />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  );
}
