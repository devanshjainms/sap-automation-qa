// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Thinking Indicator Component
 * Displays AI reasoning steps in real-time, ChatGPT-style.
 */

import React, { useState, useEffect, useRef } from "react";
import { Text, Spinner, mergeClasses } from "@fluentui/react-components";
import {
  ChevronDownRegular,
  ChevronRightRegular,
  CheckmarkCircleRegular,
  DismissCircleRegular,
  BrainCircuitRegular,
} from "@fluentui/react-icons";
import { useThinkingIndicatorStyles as useStyles } from "../../styles";

export interface ThinkingStep {
  id: string;
  parent_step_id?: string;
  agent: string;
  action: string;
  detail?: string;
  status: "pending" | "in_progress" | "complete" | "error";
  duration_ms?: number;
}

interface ThinkingIndicatorProps {
  isThinking: boolean;
  steps: ThinkingStep[];
  defaultExpanded?: boolean;
}

export const ThinkingIndicator: React.FC<ThinkingIndicatorProps> = ({
  isThinking,
  steps,
  defaultExpanded = true,
}) => {
  const styles = useStyles();
  const [isExpanded, setIsExpanded] = useState(isThinking);
  const listRef = useRef<HTMLDivElement>(null);
  const wasThinking = useRef(isThinking);

  useEffect(() => {
    if (wasThinking.current && !isThinking) {
      setIsExpanded(false);
    }
    wasThinking.current = isThinking;
  }, [isThinking]);

  useEffect(() => {
    if (isThinking) {
      setIsExpanded(true);
    }
  }, [isThinking]);

  useEffect(() => {
    if (listRef.current && isExpanded) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [steps, isExpanded]);

  if (!isThinking && steps.length === 0) {
    return null;
  }

  const getStepIcon = (status: ThinkingStep["status"]) => {
    switch (status) {
      case "pending":
        return (
          <BrainCircuitRegular
            className={mergeClasses(styles.stepIcon, styles.stepIconPending)}
          />
        );
      case "in_progress":
        return <Spinner size="extra-tiny" className={styles.stepIcon} />;
      case "complete":
        return (
          <CheckmarkCircleRegular
            className={mergeClasses(styles.stepIcon, styles.stepIconComplete)}
          />
        );
      case "error":
        return (
          <DismissCircleRegular
            className={mergeClasses(styles.stepIcon, styles.stepIconError)}
          />
        );
    }
  };

  const formatDuration = (ms: number) => {
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  return (
    <div className={styles.container}>
      <div className={styles.header} onClick={() => setIsExpanded(!isExpanded)}>
        <BrainCircuitRegular className={styles.headerIcon} />
        <Text className={styles.headerText}>
          {isThinking ? "Thinking..." : `Reasoning`}
        </Text>
        {!isThinking && (
          <Text className={styles.stepCount}>
            {steps.length} steps
          </Text>
        )}
        {isThinking ? (
          <Spinner size="extra-tiny" className={styles.headerSpinner} />
        ) : (
          isExpanded ? <ChevronDownRegular fontSize={12} /> : <ChevronRightRegular fontSize={12} />
        )}
      </div>

      <div
        ref={listRef}
        className={mergeClasses(
          styles.stepsList,
          isExpanded ? styles.stepsListExpanded : styles.stepsListCollapsed
        )}
      >
        {steps.map((step) => (
          <div
            key={step.id}
            className={mergeClasses(
              styles.step,
              step.parent_step_id ? styles.stepNested : undefined
            )}
          >
            {getStepIcon(step.status)}
            <div className={styles.stepContent}>
              <Text className={styles.stepAction}>{step.action}</Text>
              {step.detail && (
                <Text className={styles.stepDetail}> — {step.detail}</Text>
              )}
              {step.duration_ms != null && step.status === "complete" && (
                <Text className={styles.stepDuration}>
                  {formatDuration(step.duration_ms)}
                </Text>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default ThinkingIndicator;
