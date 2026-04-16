// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { Text, Button } from "@fluentui/react-components";
import { useNavigate } from "react-router-dom";

/**
 * 404 page shown for unmatched routes.
 */
export function NotFound() {
  const navigate = useNavigate();

  return (
    <div style={{ textAlign: "center", padding: "4rem 1rem" }}>
      <Text as="h1" size={800} weight="bold" block>
        404
      </Text>
      <Text size={400} block style={{ marginTop: "0.5rem" }}>
        Page not found.
      </Text>
      <Button
        appearance="primary"
        style={{ marginTop: "1.5rem" }}
        onClick={() => navigate("/")}
      >
        Go home
      </Button>
    </div>
  );
}
