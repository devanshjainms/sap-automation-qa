// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { Text } from "@fluentui/react-components";

export function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <Text size={100} weight="semibold" block>
        {label.toUpperCase()}
      </Text>
      <Text size={300}>{value}</Text>
    </div>
  );
}
