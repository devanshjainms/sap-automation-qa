// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Collapsible Sidebar Component
 * Main navigation sidebar with collapsible sections for conversations, workspaces, and job execution.
 */

import React, { useState } from "react";
import {
  Button,
  Tooltip,
  mergeClasses,
} from "@fluentui/react-components";
import {
  NavigationRegular,
  AddRegular,
} from "@fluentui/react-icons";
import { ConversationSection } from "../Sidebar/ConversationSection";
import { WorkspaceSection } from "../Sidebar/WorkspaceSection";
import { JobSection } from "../Sidebar/JobSection";
import { useChat } from "../../context";
import { useCollapsibleSidebarStyles as useStyles } from "../../styles";

interface CollapsibleSidebarProps {
  onWorkspaceSelect?: (workspaceId: string, fileName: string) => void;
}

export const CollapsibleSidebar: React.FC<CollapsibleSidebarProps> = ({
  onWorkspaceSelect,
}) => {
  const styles = useStyles();
  const { startNewChat } = useChat();
  const [isCollapsed, setIsCollapsed] = useState(false);

  const toggleSidebar = () => {
    setIsCollapsed(!isCollapsed);
  };

  return (
    <div
      className={mergeClasses(
        styles.container,
        isCollapsed && styles.containerCollapsed,
      )}
    >
      {/* Top Navigation */}
      <div className={styles.topNav}>
        <Tooltip
          content={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          relationship="label"
        >
          <Button
            icon={<NavigationRegular />}
            appearance="transparent"
            onClick={toggleSidebar}
            className={styles.navButton}
          />
        </Tooltip>
        {!isCollapsed && (
          <Tooltip content="New chat" relationship="label">
            <Button
              icon={<AddRegular />}
              appearance="transparent"
              onClick={startNewChat}
              className={styles.navButton}
            />
          </Tooltip>
        )}
      </div>

      {/* Scrollable Sections */}
      {!isCollapsed && (
        <div className={styles.sectionsContainer}>
          {/* Conversations Section */}
          <ConversationSection />

          {/* Workspaces Section */}
          <WorkspaceSection onWorkspaceSelect={onWorkspaceSelect} />

          {/* Job Execution Section */}
          <JobSection />
        </div>
      )}
    </div>
  );
};
