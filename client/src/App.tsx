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
  Tab,
  TabList,
  Button,
  Tooltip,
  Badge,
} from "@fluentui/react-components";
import {
  ChatRegular,
  ChatFilled,
  ClipboardTaskListLtrRegular,
  ClipboardTaskListLtrFilled,
  WeatherMoonRegular,
  WeatherSunnyRegular,
  bundleIcon,
} from "@fluentui/react-icons";

import { ChatProvider, WorkspaceProvider } from "./context";
import {
  ChatPanel,
  ConversationSidebar,
  JobExecutionPanel,
} from "./components";
import { healthApi } from "./api";
import { APP_STRINGS, LABELS } from "./constants";
import { useAppStyles as useStyles } from "./styles";

const ChatIcon = bundleIcon(ChatFilled, ChatRegular);
const TestIcon = bundleIcon(
  ClipboardTaskListLtrFilled,
  ClipboardTaskListLtrRegular,
);

type TabValue = "chat" | "tests";

interface AppContentProps {
  isDarkMode: boolean;
  onToggleTheme: () => void;
}

const AppContent: React.FC<AppContentProps> = ({
  isDarkMode,
  onToggleTheme,
}) => {
  const styles = useStyles();

  const [selectedTab, setSelectedTab] = useState<TabValue>("chat");
  const [isHealthy, setIsHealthy] = useState<boolean | null>(null);

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

  const handleTabSelect = (_: unknown, data: { value: TabValue }) => {
    setSelectedTab(data.value);
  };

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

  return (
    <div className={styles.root}>
      {/* Header */}
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <h1 className={styles.title}>{APP_STRINGS.APP_TITLE}</h1>
          {getStatusBadge()}
        </div>
        <div className={styles.headerRight}>
          <TabList
            selectedValue={selectedTab}
            onTabSelect={handleTabSelect as never}
          >
            <Tab icon={<ChatIcon />} value="chat">
              {LABELS.CHAT}
            </Tab>
            <Tab icon={<TestIcon />} value="tests">
              {LABELS.JOB_EXECUTION}
            </Tab>
          </TabList>
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
        {/* Sidebar */}
        <aside className={styles.sidebar}>
          <ConversationSidebar />
        </aside>

        {/* Content Area */}
        <main className={styles.content}>
          <div className={styles.tabContent}>
            {selectedTab === "chat" ? <ChatPanel /> : <JobExecutionPanel />}
          </div>
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
