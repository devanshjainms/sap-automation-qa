// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  FluentProvider,
  webLightTheme,
  webDarkTheme,
} from "@fluentui/react-components";

import { STORAGE_KEYS } from "../lib/constants";

type ThemeMode = "light" | "dark" | "system";

interface ThemeContextValue {
  mode: ThemeMode;
  isDark: boolean;
  setMode: (mode: ThemeMode) => void;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  mode: "system",
  isDark: false,
  setMode: () => {},
  toggle: () => {},
});

function resolveSystemDark(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(() => {
    const stored = localStorage.getItem(STORAGE_KEYS.theme);
    return (stored as ThemeMode) ?? "system";
  });

  const isDark = useMemo(() => {
    if (mode === "system") return resolveSystemDark();
    return mode === "dark";
  }, [mode]);

  const setMode = useCallback((m: ThemeMode) => {
    setModeState(m);
    localStorage.setItem(STORAGE_KEYS.theme, m);
  }, []);

  const toggle = useCallback(() => {
    setMode(isDark ? "light" : "dark");
  }, [isDark, setMode]);

  /* Listen for OS color scheme changes when mode is "system" */
  useEffect(() => {
    if (mode !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => setModeState("system"); // re-render
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [mode]);

  const theme = isDark ? webDarkTheme : webLightTheme;
  const value = useMemo(
    () => ({ mode, isDark, setMode, toggle }),
    [mode, isDark, setMode, toggle],
  );

  return (
    <ThemeContext.Provider value={value}>
      <FluentProvider theme={theme} style={{ height: "100%" }}>
        {children}
      </FluentProvider>
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}
