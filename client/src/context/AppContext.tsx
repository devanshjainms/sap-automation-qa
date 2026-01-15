// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * App Context
 * Global state management for application-level navigation and view state.
 */

import React, {
  createContext,
  useContext,
  useReducer,
  useCallback,
  ReactNode,
} from "react";

type ViewType = "chat" | "jobs" | "file" | "reports" | "schedule_jobs";

interface SelectedFile {
  workspaceId: string;
  fileName: string;
}

interface AppState {
  currentView: ViewType;
  selectedFile: SelectedFile | null;
  selectedWorkspaceForJobs: string | null;
  selectedJobId: string | null;
  selectedWorkspaceForReports: string | null;
  selectedScheduleId: string | null;
}

type AppAction =
  | { type: "NAVIGATE_TO_CHAT" }
  | { type: "NAVIGATE_TO_JOBS"; payload: { workspaceId: string; jobId?: string } }
  | { type: "NAVIGATE_TO_REPORTS"; payload: string }
  | { type: "NAVIGATE_TO_SCHEDULE_JOBS"; payload: string }
  | { type: "NAVIGATE_TO_FILE"; payload: SelectedFile }
  | { type: "CLOSE_FILE" };

const initialState: AppState = {
  currentView: "chat",
  selectedFile: null,
  selectedWorkspaceForJobs: null,
  selectedJobId: null,
  selectedWorkspaceForReports: null,
  selectedScheduleId: null,
};

const appReducer = (state: AppState, action: AppAction): AppState => {
  switch (action.type) {
    case "NAVIGATE_TO_CHAT":
      return {
        ...state,
        currentView: "chat",
        selectedFile: null,
        selectedWorkspaceForJobs: null,
        selectedJobId: null,
        selectedWorkspaceForReports: null,
        selectedScheduleId: null,
      };
    case "NAVIGATE_TO_JOBS":
      return {
        ...state,
        currentView: "jobs",
        selectedFile: null,
        selectedWorkspaceForJobs: action.payload.workspaceId,
        selectedJobId: action.payload.jobId || null,
        selectedWorkspaceForReports: null,
        selectedScheduleId: null,
      };
    case "NAVIGATE_TO_REPORTS":
      return {
        ...state,
        currentView: "reports",
        selectedFile: null,
        selectedWorkspaceForJobs: null,
        selectedJobId: null,
        selectedWorkspaceForReports: action.payload,
        selectedScheduleId: null,
      };
    case "NAVIGATE_TO_SCHEDULE_JOBS":
      return {
        ...state,
        currentView: "schedule_jobs",
        selectedFile: null,
        selectedWorkspaceForJobs: null,
        selectedJobId: null,
        selectedWorkspaceForReports: null,
        selectedScheduleId: action.payload,
      };
    case "NAVIGATE_TO_FILE":
      return {
        ...state,
        currentView: "file",
        selectedFile: action.payload,
        selectedWorkspaceForJobs: null,
        selectedJobId: null,
        selectedWorkspaceForReports: null,
        selectedScheduleId: null,
      };
    case "CLOSE_FILE":
      return {
        ...state,
        currentView: "chat",
        selectedFile: null,
      };
    default:
      return state;
  }
};

interface AppContextType {
  state: AppState;
  navigateToChat: () => void;
  navigateToJobs: (workspaceId: string, jobId?: string) => void;
  navigateToReports: (workspaceId: string) => void;
  navigateToScheduleJobs: (scheduleId: string) => void;
  navigateToFile: (workspaceId: string, fileName: string) => void;
  closeFile: () => void;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

export const AppProvider: React.FC<{ children: ReactNode }> = ({
  children,
}) => {
  const [state, dispatch] = useReducer(appReducer, initialState);

  const navigateToChat = useCallback(() => {
    dispatch({ type: "NAVIGATE_TO_CHAT" });
  }, []);

  const navigateToJobs = useCallback((workspaceId: string, jobId?: string) => {
    dispatch({ type: "NAVIGATE_TO_JOBS", payload: { workspaceId, jobId } });
  }, []);

  const navigateToReports = useCallback((workspaceId: string) => {
    dispatch({ type: "NAVIGATE_TO_REPORTS", payload: workspaceId });
  }, []);

  const navigateToScheduleJobs = useCallback((scheduleId: string) => {
    dispatch({ type: "NAVIGATE_TO_SCHEDULE_JOBS", payload: scheduleId });
  }, []);

  const navigateToFile = useCallback((workspaceId: string, fileName: string) => {
    dispatch({ type: "NAVIGATE_TO_FILE", payload: { workspaceId, fileName } });
  }, []);

  const closeFile = useCallback(() => {
    dispatch({ type: "CLOSE_FILE" });
  }, []);

  const value: AppContextType = {
    state,
    navigateToChat,
    navigateToJobs,
    navigateToReports,
    navigateToScheduleJobs,
    navigateToFile,
    closeFile,
  };

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
};

export const useApp = (): AppContextType => {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error("useApp must be used within an AppProvider");
  }
  return context;
};
