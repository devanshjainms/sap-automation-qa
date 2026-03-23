// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import {
  Skeleton as FluentSkeleton,
  SkeletonItem,
} from "@fluentui/react-components";

export function Skeleton() {
  return (
    <FluentSkeleton>
      <SkeletonItem style={{ height: "4rem" }} />
    </FluentSkeleton>
  );
}
