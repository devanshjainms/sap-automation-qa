// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Reasoning Trace Viewer Component
 * Displays AI reasoning steps and tool calls.
 */

import React, { useState } from "react";
import {
  makeStyles,
  tokens,
  Text,
  Accordion,
  AccordionItem,
  AccordionHeader,
  AccordionPanel,
  Badge,
} from "@fluentui/react-components";
import {
  ChevronDownRegular,
  ChevronRightRegular,
  BrainCircuitRegular,
  ToolboxRegular,
  LightbulbRegular,
  ArrowRoutingRegular,
  ErrorCircleRegular,
} from "@fluentui/react-icons";
import { ReasoningTrace } from "../../types";
import { APP_STRINGS } from "../../constants";

const useStyles = makeStyles({
  container: {
    borderTop: `1px solid ${tokens.colorNeutralStroke2}`,
    backgroundColor: tokens.colorNeutralBackground3,
  },
  header: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalS,
    padding: tokens.spacingVerticalS + " " + tokens.spacingHorizontalM,
    cursor: "pointer",
    ":hover": {
      backgroundColor: tokens.colorNeutralBackground3Hover,
    },
  },
  headerIcon: {
    color: tokens.colorBrandForeground1,
  },
  headerText: {
    flex: 1,
    fontWeight: tokens.fontWeightSemibold,
    fontSize: tokens.fontSizeBase200,
  },
  stepCount: {
    fontSize: tokens.fontSizeBase100,
    color: tokens.colorNeutralForeground3,
  },
  content: {
    padding: tokens.spacingVerticalS + " " + tokens.spacingHorizontalM,
    paddingTop: 0,
  },
  stepItem: {
    marginBottom: tokens.spacingVerticalXS,
  },
  stepHeader: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalS,
    fontSize: tokens.fontSizeBase200,
  },
  stepIcon: {
    fontSize: "16px",
  },
  stepAgent: {
    fontWeight: tokens.fontWeightSemibold,
  },
  stepPhase: {
    color: tokens.colorNeutralForeground3,
  },
  stepDescription: {
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground2,
    paddingLeft: "24px",
    marginTop: tokens.spacingVerticalXS,
  },
  stepDetails: {
    fontSize: tokens.fontSizeBase100,
    color: tokens.colorNeutralForeground3,
    paddingLeft: "24px",
    marginTop: tokens.spacingVerticalXS,
    fontFamily: "monospace",
    whiteSpace: "pre-wrap",
    backgroundColor: tokens.colorNeutralBackground1,
    padding: tokens.spacingVerticalXS + " " + tokens.spacingHorizontalS,
    borderRadius: tokens.borderRadiusSmall,
    maxHeight: "200px",
    overflowY: "auto",
  },
  errorStep: {
    color: tokens.colorPaletteRedForeground1,
  },
});

const getStepIcon = (kind: string) => {
  switch (kind) {
    case "routing":
      return <ArrowRoutingRegular />;
    case "tool_call":
      return <ToolboxRegular />;
    case "inference":
      return <LightbulbRegular />;
    case "decision":
      return <BrainCircuitRegular />;
    case "error":
      return <ErrorCircleRegular />;
    default:
      return <BrainCircuitRegular />;
  }
};

const getStepBadge = (kind: string) => {
  const colorMap: Record<
    string,
    | "brand"
    | "danger"
    | "important"
    | "informative"
    | "severe"
    | "subtle"
    | "success"
    | "warning"
  > = {
    routing: "brand",
    tool_call: "informative",
    inference: "success",
    decision: "important",
    error: "danger",
  };
  return colorMap[kind] || "subtle";
};

interface ReasoningTraceViewerProps {
  trace: ReasoningTrace | null;
}

export const ReasoningTraceViewer: React.FC<ReasoningTraceViewerProps> = ({
  trace,
}) => {
  const styles = useStyles();
  const [isExpanded, setIsExpanded] = useState(false);

  if (!trace || trace.steps.length === 0) {
    return null;
  }

  return (
    <div className={styles.container}>
      <div className={styles.header} onClick={() => setIsExpanded(!isExpanded)}>
        {isExpanded ? <ChevronDownRegular /> : <ChevronRightRegular />}
        <BrainCircuitRegular className={styles.headerIcon} />
        <Text className={styles.headerText}>
          {isExpanded ? APP_STRINGS.TRACE_COLLAPSE : APP_STRINGS.TRACE_EXPAND}
        </Text>
        <Text className={styles.stepCount}>{trace.steps.length} steps</Text>
      </div>

      {isExpanded && (
        <div className={styles.content}>
          <Accordion multiple collapsible>
            {trace.steps.map((step, index) => (
              <AccordionItem
                key={step.id}
                value={step.id}
                className={styles.stepItem}
              >
                <AccordionHeader expandIconPosition="start">
                  <div className={styles.stepHeader}>
                    <span className={styles.stepIcon}>
                      {getStepIcon(step.kind)}
                    </span>
                    <Badge
                      appearance="filled"
                      color={getStepBadge(step.kind)}
                      size="small"
                    >
                      {step.kind}
                    </Badge>
                    <Text className={styles.stepAgent}>{step.agent}</Text>
                    <Text className={styles.stepPhase}>• {step.phase}</Text>
                    {step.error && (
                      <ErrorCircleRegular className={styles.errorStep} />
                    )}
                  </div>
                </AccordionHeader>
                <AccordionPanel>
                  <Text className={styles.stepDescription}>
                    {step.description}
                  </Text>
                  {(Object.keys(step.input_snapshot).length > 0 ||
                    Object.keys(step.output_snapshot).length > 0) && (
                    <div className={styles.stepDetails}>
                      {Object.keys(step.input_snapshot).length > 0 && (
                        <>
                          <strong>Input:</strong>
                          {"\n"}
                          {JSON.stringify(step.input_snapshot, null, 2)}
                        </>
                      )}
                      {Object.keys(step.output_snapshot).length > 0 && (
                        <>
                          {"\n\n"}
                          <strong>Output:</strong>
                          {"\n"}
                          {JSON.stringify(step.output_snapshot, null, 2)}
                        </>
                      )}
                    </div>
                  )}
                  {step.error && (
                    <Text className={styles.errorStep}>
                      Error: {step.error}
                    </Text>
                  )}
                </AccordionPanel>
              </AccordionItem>
            ))}
          </Accordion>
        </div>
      )}
    </div>
  );
};
