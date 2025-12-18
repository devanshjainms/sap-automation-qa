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
  mergeClasses,
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
    maxWidth: "900px",
    margin: "0 auto",
    padding: `${tokens.spacingVerticalM} 0`,
    width: "100%",
    overflow: "hidden",
  },
  header: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalS,
    padding: `4px 12px`,
    cursor: "pointer",
    borderRadius: tokens.borderRadiusCircular,
    backgroundColor: tokens.colorNeutralBackground3,
    width: "fit-content",
    transition: "all 0.2s ease",
    ":hover": {
      backgroundColor: tokens.colorNeutralBackground3Hover,
    },
  },
  headerIcon: {
    color: tokens.colorBrandForeground1,
    fontSize: "14px",
  },
  headerText: {
    fontSize: tokens.fontSizeBase100,
    color: tokens.colorNeutralForeground2,
    fontWeight: tokens.fontWeightMedium,
  },
  stepCount: {
    fontSize: tokens.fontSizeBase100,
    color: tokens.colorNeutralForeground4,
    marginLeft: tokens.spacingHorizontalXS,
  },
  content: {
    padding: tokens.spacingVerticalM,
    marginTop: tokens.spacingVerticalS,
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusMedium,
    backgroundColor: tokens.colorNeutralBackground2,
  },
  accordion: {
    display: "flex",
    flexDirection: "column",
    gap: tokens.spacingVerticalXS,
  },
  stepItem: {
    backgroundColor: tokens.colorNeutralBackground1,
    borderRadius: tokens.borderRadiusSmall,
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    transition: "all 0.2s ease",
    ":hover": {
      border: `1px solid ${tokens.colorBrandStroke1}`,
    },
  },
  stepNested: {
    marginLeft: "20px",
    position: "relative",
    ":before": {
      content: '""',
      position: "absolute",
      left: "-12px",
      top: "0",
      bottom: "0",
      width: "2px",
      backgroundColor: tokens.colorNeutralStroke2,
    },
  },
  stepHeader: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalS,
    width: "100%",
    paddingRight: tokens.spacingHorizontalM,
  },
  stepIcon: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    width: "24px",
    height: "24px",
    fontSize: "16px",
    color: tokens.colorBrandForeground1,
  },
  stepInfo: {
    display: "flex",
    flexDirection: "column",
    flex: 1,
  },
  stepTitle: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalXS,
  },
  stepAgent: {
    fontWeight: tokens.fontWeightBold,
    fontSize: tokens.fontSizeBase200,
  },
  stepPhase: {
    color: tokens.colorNeutralForeground3,
    fontSize: tokens.fontSizeBase100,
    textTransform: "uppercase",
    letterSpacing: "0.5px",
  },
  stepMeta: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalS,
    marginLeft: "auto",
  },
  duration: {
    fontSize: tokens.fontSizeBase100,
    color: tokens.colorNeutralForeground4,
    fontFamily: "monospace",
  },
  stepDescription: {
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground2,
    marginBottom: tokens.spacingVerticalS,
    display: "block",
    lineHeight: tokens.lineHeightBase300,
  },
  snapshotContainer: {
    display: "flex",
    flexDirection: "column",
    gap: tokens.spacingVerticalS,
    marginTop: tokens.spacingVerticalS,
  },
  snapshotBox: {
    backgroundColor: tokens.colorNeutralBackground3,
    borderRadius: tokens.borderRadiusSmall,
    padding: tokens.spacingVerticalS,
    border: `1px solid ${tokens.colorNeutralStroke2}`,
  },
  snapshotTitle: {
    fontSize: tokens.fontSizeBase100,
    fontWeight: tokens.fontWeightBold,
    color: tokens.colorBrandForeground1,
    marginBottom: tokens.spacingVerticalXS,
    display: "block",
    textTransform: "uppercase",
    letterSpacing: "1px",
  },
  snapshotCode: {
    fontSize: tokens.fontSizeBase100,
    fontFamily: "Consolas, 'Courier New', monospace",
    whiteSpace: "pre-wrap",
    color: tokens.colorNeutralForeground1,
    margin: 0,
    lineHeight: "1.4",
  },
  panel: {
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalM}`,
    paddingLeft: "48px",
  },
  errorStep: {
    color: tokens.colorPaletteRedForeground1,
    backgroundColor: tokens.colorPaletteRedBackground1,
    padding: tokens.spacingVerticalXS,
    borderRadius: tokens.borderRadiusSmall,
    marginTop: tokens.spacingVerticalS,
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalXS,
    fontSize: tokens.fontSizeBase200,
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

const formatDuration = (ms?: number) => {
  if (ms === undefined || ms === null) return null;
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
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
        <div className={styles.stepCount}>{trace.steps.length} steps</div>
      </div>

      {isExpanded && (
        <div className={styles.content}>
          <Accordion multiple collapsible className={styles.accordion}>
            {trace.steps.map((step) => (
              <AccordionItem
                key={step.id}
                value={step.id}
                className={mergeClasses(
                  styles.stepItem,
                  step.parent_step_id ? styles.stepNested : undefined
                )}
              >
                <AccordionHeader expandIconPosition="start">
                  <div className={styles.stepHeader}>
                    <span className={styles.stepIcon}>
                      {getStepIcon(step.kind)}
                    </span>
                    <div className={styles.stepInfo}>
                      <div className={styles.stepTitle}>
                        <Text className={styles.stepAgent}>{step.agent}</Text>
                        <Badge
                          appearance="tint"
                          color={getStepBadge(step.kind)}
                          size="tiny"
                        >
                          {step.kind}
                        </Badge>
                      </div>
                      <Text className={styles.stepPhase}>{step.phase}</Text>
                    </div>
                    <div className={styles.stepMeta}>
                      {step.duration_ms !== undefined && (
                        <Text className={styles.duration}>
                          {formatDuration(step.duration_ms)}
                        </Text>
                      )}
                      {step.error && (
                        <ErrorCircleRegular className={styles.errorStep} />
                      )}
                    </div>
                  </div>
                </AccordionHeader>
                <AccordionPanel className={styles.panel}>
                  <Text className={styles.stepDescription}>
                    {step.description}
                  </Text>
                  
                  <div className={styles.snapshotContainer}>
                    {Object.keys(step.input_snapshot).length > 0 && (
                      <div className={styles.snapshotBox}>
                        <Text className={styles.snapshotTitle}>Input Snapshot</Text>
                        <pre className={styles.snapshotCode}>
                          {JSON.stringify(step.input_snapshot, null, 2)}
                        </pre>
                      </div>
                    )}
                    
                    {Object.keys(step.output_snapshot).length > 0 && (
                      <div className={styles.snapshotBox}>
                        <Text className={styles.snapshotTitle}>Output Snapshot</Text>
                        <pre className={styles.snapshotCode}>
                          {JSON.stringify(step.output_snapshot, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>

                  {step.error && (
                    <div className={styles.errorStep}>
                      <ErrorCircleRegular />
                      <Text>Error: {step.error}</Text>
                    </div>
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
