// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Workspace File Viewer Component
 * Displays and allows editing of workspace configuration files.
 */

import React, { useState, useEffect } from "react";
import {
  Text,
  Button,
  Spinner,
  Textarea,
  mergeClasses,
  Tooltip,
} from "@fluentui/react-components";
import {
  SaveRegular,
  DismissRegular,
} from "@fluentui/react-icons";
import { workspacesApi } from "../../api";
import { useWorkspaceFileViewerStyles as useStyles } from "../../styles";

interface WorkspaceFileViewerProps {
  workspaceId: string;
  fileName: string;
  onClose: () => void;
}

export const WorkspaceFileViewer: React.FC<WorkspaceFileViewerProps> = ({
  workspaceId,
  fileName,
  onClose,
}) => {
  const styles = useStyles();
  const [content, setContent] = useState("");
  const [originalContent, setOriginalContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadFileContent();
  }, [workspaceId, fileName]);

  const loadFileContent = async () => {
    setLoading(true);
    setError(null);
    try {
      const fileContent = await workspacesApi.getFileContent(workspaceId, fileName);
      setContent(fileContent);
      setOriginalContent(fileContent);
    } catch (err: any) {
      const errorMsg = err?.response?.data?.detail || err?.message || "Failed to load file content";
      setError(errorMsg);
      console.error("Error loading file:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      await workspacesApi.updateFileContent(workspaceId, fileName, content);
      setOriginalContent(content);
    } catch (err) {
      setError("Failed to save file");
      console.error("Error saving file:", err);
    } finally {
      setSaving(false);
    }
  };

  const hasChanges = content !== originalContent;

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <Text className={styles.title}>{fileName}</Text>
          <Text className={styles.subtitle}>{workspaceId}</Text>
        </div>
        <div className={styles.headerRight}>
          {hasChanges && (
            <Tooltip content="Save changes" relationship="label">
              <Button
                icon={<SaveRegular />}
                appearance="primary"
                size="small"
                onClick={handleSave}
                disabled={saving}
              >
                {saving ? <Spinner size="tiny" /> : "Save"}
              </Button>
            </Tooltip>
          )}
          <Tooltip content="Close" relationship="label">
            <Button
              icon={<DismissRegular />}
              appearance="subtle"
              size="small"
              onClick={onClose}
            />
          </Tooltip>
        </div>
      </div>

      {/* Content */}
      <div className={styles.content}>
        {loading ? (
          <div className={styles.loadingContainer}>
            <Spinner />
            <Text>Loading file...</Text>
          </div>
        ) : error ? (
          <div className={styles.errorContainer}>
            <Text className={styles.errorText}>{error}</Text>
            <Button onClick={loadFileContent} size="small">
              Retry
            </Button>
          </div>
        ) : (
          <Textarea
            value={content}
            onChange={(_, data) => setContent(data.value)}
            className={styles.editor}
            resize="none"
            appearance="filled-lighter"
            style={{ flex: 1, height: '100%', maxHeight: 'none' }}
            textarea={{ style: { height: '100%', maxHeight: 'none' } }}
          />
        )}
      </div>

      {hasChanges && (
        <div className={styles.footer}>
          <Text className={styles.footerText}>You have unsaved changes</Text>
        </div>
      )}
    </div>
  );
};
