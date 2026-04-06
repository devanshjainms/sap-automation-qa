// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Fetches MCP tool metadata once at mount and caches it for the
 * lifetime of the component tree.  Provides a ``Map<name, ToolMeta>``
 * for O(1) lookups in the tool-call renderer.
 */

import { useEffect, useState } from "react";
import { getToolMetadata } from "../lib/api";
import type { ToolMeta } from "../lib/types";

let cachedRegistry: Map<string, ToolMeta> | null = null;

export function useToolRegistry(): Map<string, ToolMeta> {
  const [registry, setRegistry] = useState<Map<string, ToolMeta>>(
    () => cachedRegistry ?? new Map(),
  );

  useEffect(() => {
    if (cachedRegistry) return;
    let cancelled = false;
    getToolMetadata()
      .then((tools) => {
        if (cancelled) return;
        const map = new Map(tools.map((t) => [t.name, t]));
        cachedRegistry = map;
        setRegistry(map);
      })
      .catch(() => {
        /* endpoint unavailable — render with empty registry */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return registry;
}
