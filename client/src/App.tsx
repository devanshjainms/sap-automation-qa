// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * App Component
 * Root application component with providers and main layout.
 */

import React, { useState, useCallback, useEffect } from "react";
import {
  FluentProvider,
  webLightTheme,
  webDarkTheme,
  Button,
  Tooltip,
  Badge,
} from "@fluentui/react-components";
import {
  WeatherMoonRegular,
  WeatherSunnyRegular,
} from "@fluentui/react-icons";

import { ChatProvider, WorkspaceProvider } from "./context";
import {
  ChatPanel,
  CollapsibleSidebar,
  JobExecutionPanel,
  WorkspaceFileViewer,
} from "./components";
import { healthApi } from "./api";
import { APP_STRINGS } from "./constants";
import { useAppStyles as useStyles } from "./styles";

interface AppContentProps {
  isDarkMode: boolean;
  onToggleTheme: () => void;
}

const AppContent: React.FC<AppContentProps> = ({
  isDarkMode,
  onToggleTheme,
}) => {
  const styles = useStyles();

  const [isHealthy, setIsHealthy] = useState<boolean | null>(null);
  const [showJobPanel, setShowJobPanel] = useState(false);
  const [selectedWorkspaceForJobs, setSelectedWorkspaceForJobs] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<{
    workspaceId: string;
    fileName: string;
  } | null>(null);

  // Check API health on mount
  useEffect(() => {
    const checkHealth = async () => {
      try {
        const response = await healthApi.check();
        setIsHealthy(response.status === "healthy");
      } catch {
        setIsHealthy(false);
      }
    };
    checkHealth();

    // Recheck every 30 seconds
    const interval = setInterval(checkHealth, 30000);
    return () => clearInterval(interval);
  }, []);

  const getStatusBadge = () => {
    if (isHealthy === null) {
      return (
        <Badge
          appearance="outline"
          color="warning"
          className={styles.statusBadge}
        >
          Checking...
        </Badge>
      );
    }
    return isHealthy ? (
      <Badge appearance="filled" color="success" className={styles.statusBadge}>
        Connected
      </Badge>
    ) : (
      <Badge appearance="filled" color="danger" className={styles.statusBadge}>
        Disconnected
      </Badge>
    );
  };

  const handleWorkspaceSelect = (workspaceId: string, fileName: string) => {
    setSelectedFile({ workspaceId, fileName });
    setShowJobPanel(false);
    setSelectedWorkspaceForJobs(null);
  };

  const handleJobsClick = (workspaceId: string) => {
    setSelectedWorkspaceForJobs(workspaceId);
    setShowJobPanel(true);
    setSelectedFile(null);
  };

  const handleCloseFile = () => {
    setSelectedFile(null);
  };

  return (
    <div className={styles.root}>
      {/* Header */}
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <h1 className={styles.title}>{APP_STRINGS.APP_TITLE}</h1>
          {getStatusBadge()}
        </div>
        <div className={styles.headerRight}>
          <Tooltip
            content={
              isDarkMode ? "Switch to light mode" : "Switch to dark mode"
            }
            relationship="label"
          >
            <Button
              appearance="subtle"
              icon={
                isDarkMode ? <WeatherSunnyRegular /> : <WeatherMoonRegular />
              }
              onClick={onToggleTheme}
            />
          </Tooltip>
        </div>
      </header>

      {/* Main Content */}
      <div className={styles.mainContainer}>
        {/* Collapsible Sidebar */}
        <CollapsibleSidebar 
          onWorkspaceSelect={handleWorkspaceSelect}
          onJobsClick={handleJobsClick}
        />

        {/* Content Area */}
        <main className={styles.content}>
          {selectedFile ? (
            <WorkspaceFileViewer
              workspaceId={selectedFile.workspaceId}
              fileName={selectedFile.fileName}
              onClose={handleCloseFile}
            />
          ) : showJobPanel ? (
            <JobExecutionPanel workspaceId={selectedWorkspaceForJobs || undefined} />
          ) : (
            <ChatPanel />
          )}
        </main>
      </div>
    </div>
  );
};

const App: React.FC = () => {
  const [isDarkMode, setIsDarkMode] = useState(() => {
    // Check for saved preference or system preference
    const saved = localStorage.getItem("theme");
    if (saved) return saved === "dark";
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
  });

  const toggleTheme = useCallback(() => {
    setIsDarkMode((prev) => {
      const newValue = !prev;
      localStorage.setItem("theme", newValue ? "dark" : "light");
      return newValue;
    });
  }, []);

  return (
    <FluentProvider theme={isDarkMode ? webDarkTheme : webLightTheme}>
      <WorkspaceProvider>
        <ChatProvider>
          <AppContent isDarkMode={isDarkMode} onToggleTheme={toggleTheme} />
        </ChatProvider>
      </WorkspaceProvider>
    </FluentProvider>
  );
};

export default App;
