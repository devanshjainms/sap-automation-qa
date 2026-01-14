// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Job Section Component
 * Displays job execution interface in the sidebar.
 */

import React, { useState } from "react";
import {
  Text,
  Button,
  mergeClasses,
} from "@fluentui/react-components";
import {
  ChevronDownRegular,
  ChevronRightRegular,
  PlayRegular,
} from "@fluentui/react-icons";
import { useJobSectionStyles as useStyles } from "../../styles";

interface JobSectionProps {
  onJobViewToggle?: () => void;
}

export const JobSection: React.FC<JobSectionProps> = ({ onJobViewToggle }) => {
  const styles = useStyles();
  const [isExpanded, setIsExpanded] = useState(false);

  const toggleExpanded = () => {
    setIsExpanded(!isExpanded);
    if (onJobViewToggle) {
      onJobViewToggle();
    }
  };

  return (
    <div className={styles.section}>
      {/* Section Header */}
      <div className={styles.sectionHeader} onClick={toggleExpanded}>
        <Button
          icon={isExpanded ? <ChevronDownRegular /> : <ChevronRightRegular />}
          appearance="transparent"
          size="small"
          className={styles.expandButton}
        />
        <Text className={styles.sectionTitle}>Job Execution</Text>
      </div>

      {/* Section Content */}
      {isExpanded && (
        <div className={styles.sectionContent}>
          <div className={styles.jobHint}>
            <PlayRegular className={styles.jobIcon} />
            <Text className={styles.jobText}>
              Click to expand job execution panel
            </Text>
          </div>
        </div>
      )}
    </div>
  );
};
