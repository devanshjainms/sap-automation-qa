// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { useEffect } from "react";
import { useTheme } from "../hooks/useTheme";

/**
 * Syncs the FluentUI dark mode state to the `<html>` element's class list
 * so CopilotKit v2 components pick up the correct dark/light theme.
 *
 * CopilotKit uses `.dark [data-copilotkit]` selectors for dark mode.
 */
export function DarkModeSync() {
  const { isDark } = useTheme();

  useEffect(() => {
    document.documentElement.classList.toggle("dark", isDark);
  }, [isDark]);

  return null;
}
