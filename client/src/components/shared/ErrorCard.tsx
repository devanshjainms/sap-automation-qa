// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import {
  MessageBar,
  MessageBarBody,
} from "@fluentui/react-components";

export function ErrorCard({ message }: { message: string }) {
  return (
    <MessageBar intent="error">
      <MessageBarBody>{message}</MessageBarBody>
    </MessageBar>
  );
}
