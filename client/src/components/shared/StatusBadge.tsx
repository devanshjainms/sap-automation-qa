// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { Badge } from "@fluentui/react-components";
import { STATUS_BADGE_COLORS } from "../../lib/constants";

export function StatusBadge({ status }: { status: string }) {
  return (
    <Badge
      appearance="filled"
      color={STATUS_BADGE_COLORS[status] ?? "informative"}
      size="small"
    >
      {status}
    </Badge>
  );
}
