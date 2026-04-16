// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Spinner } from "@fluentui/react-components";
import { ErrorBoundary } from "./components/shared/ErrorBoundary";
import { AppShell } from "./components/layout/AppShell";
import { NotFound } from "./pages/NotFound";
import { strings } from "./lib/strings";
import { useAppStyles } from "./styles/app.styles";

/* Lazy-loaded page components for code splitting. */
const ChatPage = lazy(() => import("./pages/ChatPage"));
const Dashboard = lazy(
  () => import("./pages/Dashboard").then((m) => ({ default: m.Dashboard })),
);
const Jobs = lazy(
  () => import("./pages/Jobs").then((m) => ({ default: m.Jobs })),
);
const JobDetailPage = lazy(
  () =>
    import("./pages/JobDetailPage").then((m) => ({
      default: m.JobDetailPage,
    })),
);
const Schedules = lazy(
  () => import("./pages/Schedules").then((m) => ({ default: m.Schedules })),
);
const Workspaces = lazy(
  () => import("./pages/Workspaces").then((m) => ({ default: m.Workspaces })),
);
const Status = lazy(
  () => import("./pages/Status").then((m) => ({ default: m.Status })),
);

function PageSuspense({ children }: { children: React.ReactNode }) {
  const classes = useAppStyles();
  return (
    <Suspense
      fallback={
        <div className={classes.suspenseFallback}>
          <Spinner size="small" label={strings.shared.loading} />
        </div>
      }
    >
      {children}
    </Suspense>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <ErrorBoundary>
        <Routes>
            <Route element={<AppShell />}>
              <Route
                index
                element={
                  <PageSuspense>
                    <ChatPage />
                  </PageSuspense>
                }
              />
              <Route
                path="chat/:conversationId"
                element={
                  <PageSuspense>
                    <ChatPage />
                  </PageSuspense>
                }
              />
              <Route
                path="dashboard"
                element={
                  <PageSuspense>
                    <Dashboard />
                  </PageSuspense>
                }
              />
              <Route
                path="jobs"
                element={
                  <PageSuspense>
                    <Jobs />
                  </PageSuspense>
                }
              />
              <Route
                path="jobs/:id"
                element={
                  <PageSuspense>
                    <JobDetailPage />
                  </PageSuspense>
                }
              />
              <Route
                path="schedules"
                element={
                  <PageSuspense>
                    <Schedules />
                  </PageSuspense>
                }
              />
              <Route
                path="workspaces"
                element={
                  <PageSuspense>
                    <Workspaces />
                  </PageSuspense>
                }
              />
              <Route
                path="status"
                element={
                  <PageSuspense>
                    <Status />
                  </PageSuspense>
                }
              />
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </ErrorBoundary>
    </BrowserRouter>
  );
}
