// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { Badge } from "@fluentui/react-components";
import type { BadgeProps } from "@fluentui/react-components";

const COLOR_MAP: Record<string, BadgeProps["color"]> = {
  completed: "success",
  running: "brand",
  queued: "informative",
  failed: "danger",
  cancelled: "warning",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <Badge
      appearance="filled"
      color={COLOR_MAP[status] ?? "informative"}
      size="small"
    >
      {status}
    </Badge>
  );
}
