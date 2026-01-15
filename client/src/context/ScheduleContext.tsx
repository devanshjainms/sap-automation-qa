// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Schedule Context
 * State management for schedule CRUD operations.
 */

import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  ReactNode,
} from "react";
import { Schedule, CreateScheduleRequest, UpdateScheduleRequest } from "../types";
import { schedulesApi } from "../api";

interface ScheduleState {
  schedules: Schedule[];
  isLoading: boolean;
  error: string | null;
}

interface ScheduleContextType {
  state: ScheduleState;
  loadSchedules: () => Promise<void>;
  getScheduleById: (scheduleId: string) => Schedule | undefined;
  createSchedule: (request: CreateScheduleRequest) => Promise<Schedule>;
  updateSchedule: (scheduleId: string, request: UpdateScheduleRequest) => Promise<Schedule>;
  deleteSchedule: (scheduleId: string) => Promise<void>;
  toggleSchedule: (scheduleId: string) => Promise<Schedule>;
}

const ScheduleContext = createContext<ScheduleContextType | undefined>(
  undefined,
);

export const ScheduleProvider: React.FC<{ children: ReactNode }> = ({
  children,
}) => {
  const [state, setState] = useState<ScheduleState>({
    schedules: [],
    isLoading: false,
    error: null,
  });

  const loadSchedules = useCallback(async () => {
    setState((prev) => ({ ...prev, isLoading: true, error: null }));

    try {
      const response = await schedulesApi.list();
      const schedules: Schedule[] = response.schedules;

      setState((prev) => ({
        ...prev,
        schedules,
        isLoading: false,
      }));
    } catch (error) {
      console.error("Failed to load schedules:", error);
      setState((prev) => ({
        ...prev,
        isLoading: false,
        error:
          error instanceof Error ? error.message : "Failed to load schedules",
      }));
    }
  }, []);

  const getScheduleById = useCallback(
    (scheduleId: string): Schedule | undefined => {
      return state.schedules.find((s) => s.id === scheduleId);
    },
    [state.schedules],
  );

  const createSchedule = useCallback(
    async (request: CreateScheduleRequest): Promise<Schedule> => {
      setState((prev) => ({ ...prev, isLoading: true, error: null }));

      try {
        const schedule = await schedulesApi.create(request);
        setState((prev) => ({
          ...prev,
          schedules: [...prev.schedules, schedule],
          isLoading: false,
        }));
        return schedule;
      } catch (error) {
        console.error("Failed to create schedule:", error);
        const errorMsg =
          error instanceof Error ? error.message : "Failed to create schedule";
        setState((prev) => ({
          ...prev,
          isLoading: false,
          error: errorMsg,
        }));
        throw error;
      }
    },
    [],
  );

  const updateSchedule = useCallback(
    async (
      scheduleId: string,
      request: UpdateScheduleRequest,
    ): Promise<Schedule> => {
      setState((prev) => ({ ...prev, isLoading: true, error: null }));

      try {
        const schedule = await schedulesApi.update(scheduleId, request);
        setState((prev) => ({
          ...prev,
          schedules: prev.schedules.map((s) =>
            s.id === scheduleId ? schedule : s,
          ),
          isLoading: false,
        }));
        return schedule;
      } catch (error) {
        console.error("Failed to update schedule:", error);
        const errorMsg =
          error instanceof Error ? error.message : "Failed to update schedule";
        setState((prev) => ({
          ...prev,
          isLoading: false,
          error: errorMsg,
        }));
        throw error;
      }
    },
    [],
  );

  const deleteSchedule = useCallback(async (scheduleId: string): Promise<void> => {
    setState((prev) => ({ ...prev, isLoading: true, error: null }));

    try {
      await schedulesApi.delete(scheduleId);
      setState((prev) => ({
        ...prev,
        schedules: prev.schedules.filter((s) => s.id !== scheduleId),
        isLoading: false,
      }));
    } catch (error) {
      console.error("Failed to delete schedule:", error);
      const errorMsg =
        error instanceof Error ? error.message : "Failed to delete schedule";
      setState((prev) => ({
        ...prev,
        isLoading: false,
        error: errorMsg,
      }));
      throw error;
    }
  }, []);

  const toggleSchedule = useCallback(
    async (scheduleId: string): Promise<Schedule> => {
      setState((prev) => ({ ...prev, isLoading: true, error: null }));

      try {
        const schedule = await schedulesApi.toggle(scheduleId);
        setState((prev) => ({
          ...prev,
          schedules: prev.schedules.map((s) =>
            s.id === scheduleId ? schedule : s,
          ),
          isLoading: false,
        }));
        return schedule;
      } catch (error) {
        console.error("Failed to toggle schedule:", error);
        const errorMsg =
          error instanceof Error ? error.message : "Failed to toggle schedule";
        setState((prev) => ({
          ...prev,
          isLoading: false,
          error: errorMsg,
        }));
        throw error;
      }
    },
    [],
  );

  const value: ScheduleContextType = {
    state,
    loadSchedules,
    getScheduleById,
    createSchedule,
    updateSchedule,
    deleteSchedule,
    toggleSchedule,
  };

  return (
    <ScheduleContext.Provider value={value}>
      {children}
    </ScheduleContext.Provider>
  );
};

export const useSchedule = (): ScheduleContextType => {
  const context = useContext(ScheduleContext);
  if (!context) {
    throw new Error("useSchedule must be used within a ScheduleProvider");
  }
  return context;
};
