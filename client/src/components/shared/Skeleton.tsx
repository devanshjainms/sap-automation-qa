// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import {
  Skeleton as FluentSkeleton,
  SkeletonItem,
} from "@fluentui/react-components";
import { useStyles } from "../../styles/skeleton.styles";

export function Skeleton() {
  const classes = useStyles();
  return (
    <FluentSkeleton>
      <SkeletonItem className={classes.item} />
    </FluentSkeleton>
  );
}
