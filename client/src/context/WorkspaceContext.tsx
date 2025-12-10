// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Workspace Context
 * State management for multi-workspace selection functionality.
 */

import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  ReactNode,
} from "react";
import { Workspace } from "../types";
import { workspacesApi } from "../api";
import { APP_CONFIG } from "../constants";

interface WorkspaceState {
  workspaces: Workspace[];
  isLoading: boolean;
  error: string | null;
  selectedWorkspaceIds: string[];
}

interface WorkspaceContextType {
  state: WorkspaceState;
  loadWorkspaces: () => Promise<void>;
  selectWorkspace: (workspaceId: string) => void;
  deselectWorkspace: (workspaceId: string) => void;
  clearWorkspaces: () => void;
  toggleWorkspace: (workspaceId: string) => void;
  getWorkspaceById: (workspaceId: string) => Workspace | undefined;
  selectedWorkspaceIds: string[];
}

const WorkspaceContext = createContext<WorkspaceContextType | undefined>(
  undefined,
);

const loadSavedWorkspaces = (): string[] => {
  const saved = localStorage.getItem(
    APP_CONFIG.STORAGE_KEYS.SELECTED_WORKSPACE,
  );
  if (!saved) return [];
  try {
    const parsed = JSON.parse(saved);
    return Array.isArray(parsed) ? parsed : [saved]; // Handle legacy single value
  } catch {
    return saved ? [saved] : []; // Handle legacy single value
  }
};

export const WorkspaceProvider: React.FC<{ children: ReactNode }> = ({
  children,
}) => {
  const [state, setState] = useState<WorkspaceState>({
    workspaces: [],
    isLoading: false,
    error: null,
    selectedWorkspaceIds: loadSavedWorkspaces(),
  });

  const loadWorkspaces = useCallback(async () => {
    setState((prev) => ({ ...prev, isLoading: true, error: null }));

    try {
      const response = await workspacesApi.list();

      const workspaces: Workspace[] = response.workspaces.map((w) => ({
        workspace_id: w.workspace_id,
        env: w.env,
        region: w.region,
        deployment_code: w.deployment_code,
        sid: w.sid,
      }));

      setState((prev) => ({
        ...prev,
        workspaces,
        isLoading: false,
      }));
    } catch (error) {
      console.error("Failed to load workspaces:", error);
      setState((prev) => ({
        ...prev,
        isLoading: false,
        error:
          error instanceof Error ? error.message : "Failed to load workspaces",
      }));
    }
  }, []);

  const saveToStorage = useCallback((ids: string[]) => {
    if (ids.length > 0) {
      localStorage.setItem(
        APP_CONFIG.STORAGE_KEYS.SELECTED_WORKSPACE,
        JSON.stringify(ids),
      );
    } else {
      localStorage.removeItem(APP_CONFIG.STORAGE_KEYS.SELECTED_WORKSPACE);
    }
  }, []);

  const selectWorkspace = useCallback(
    (workspaceId: string) => {
      setState((prev) => {
        if (prev.selectedWorkspaceIds.includes(workspaceId)) {
          return prev; // Already selected
        }
        const newIds = [...prev.selectedWorkspaceIds, workspaceId];
        saveToStorage(newIds);
        return { ...prev, selectedWorkspaceIds: newIds };
      });
    },
    [saveToStorage],
  );

  const deselectWorkspace = useCallback(
    (workspaceId: string) => {
      setState((prev) => {
        const newIds = prev.selectedWorkspaceIds.filter(
          (id) => id !== workspaceId,
        );
        saveToStorage(newIds);
        return { ...prev, selectedWorkspaceIds: newIds };
      });
    },
    [saveToStorage],
  );

  const clearWorkspaces = useCallback(() => {
    saveToStorage([]);
    setState((prev) => ({ ...prev, selectedWorkspaceIds: [] }));
  }, [saveToStorage]);

  const toggleWorkspace = useCallback(
    (workspaceId: string) => {
      setState((prev) => {
        const isSelected = prev.selectedWorkspaceIds.includes(workspaceId);
        const newIds = isSelected
          ? prev.selectedWorkspaceIds.filter((id) => id !== workspaceId)
          : [...prev.selectedWorkspaceIds, workspaceId];
        saveToStorage(newIds);
        return { ...prev, selectedWorkspaceIds: newIds };
      });
    },
    [saveToStorage],
  );

  const getWorkspaceById = useCallback(
    (workspaceId: string): Workspace | undefined => {
      return state.workspaces.find((w) => w.workspace_id === workspaceId);
    },
    [state.workspaces],
  );

  useEffect(() => {
    loadWorkspaces();
  }, [loadWorkspaces]);

  const value: WorkspaceContextType = {
    state,
    loadWorkspaces,
    selectWorkspace,
    deselectWorkspace,
    clearWorkspaces,
    toggleWorkspace,
    getWorkspaceById,
    selectedWorkspaceIds: state.selectedWorkspaceIds,
  };

  return (
    <WorkspaceContext.Provider value={value}>
      {children}
    </WorkspaceContext.Provider>
  );
};

export const useWorkspace = (): WorkspaceContextType => {
  const context = useContext(WorkspaceContext);
  if (!context) {
    throw new Error("useWorkspace must be used within a WorkspaceProvider");
  }
  return context;
};
