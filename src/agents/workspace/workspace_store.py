# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Workspace models for SAP QA testing.
"""

import shutil
from pathlib import Path
from typing import Optional

from src.agents.models.workspace import WorkspaceMetadata


class WorkspaceStore:
    """Store for managing SAP QA workspaces."""

    def __init__(self, root_path: str | Path) -> None:
        """Initialize workspace store.

        :param root_path: Root directory containing all workspaces
        :type root_path: str | Path
        """
        self.root_path = Path(root_path)
        if not self.root_path.exists():
            self.root_path.mkdir(parents=True, exist_ok=True)

    def list_workspaces(self) -> list[WorkspaceMetadata]:
        """List all workspaces in the store.

        :returns: List of workspace metadata objects
        :rtype: list[WorkspaceMetadata]
        """
        workspaces = []
        if not self.root_path.exists():
            return workspaces

        for item in self.root_path.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                metadata = WorkspaceMetadata.from_workspace_id(item.name, self.root_path)
                if metadata:
                    workspaces.append(metadata)

        return workspaces

    def get_workspace(self, workspace_id: str) -> Optional[WorkspaceMetadata]:
        """Get workspace metadata by ID.

        :param workspace_id: Workspace identifier
        :type workspace_id: str
        :returns: WorkspaceMetadata if exists, None otherwise
        :rtype: Optional[WorkspaceMetadata]
        """
        workspace_path = self.root_path / workspace_id
        if not workspace_path.exists():
            return None

        return WorkspaceMetadata.from_workspace_id(workspace_id, self.root_path)

    def create_workspace(
        self,
        env: str,
        region: str,
        deployment_code: str,
        sid: str,
        template_dir: Optional[Path] = None,
    ) -> tuple[WorkspaceMetadata, bool]:
        """Create a new workspace.

        :param env: Environment (DEV, QA, PROD)
        :type env: str
        :param region: Region code (WEEU, EAUS, etc.)
        :type region: str
        :param deployment_code: Deployment code (SAP01, SAP02, etc.)
        :type deployment_code: str
        :param sid: SAP System ID
        :type sid: str
        :param template_dir: Optional template directory to copy from
        :type template_dir: Optional[Path]
        :returns: Tuple of (WorkspaceMetadata, created) where created is True if new, False if existed
        :rtype: tuple[WorkspaceMetadata, bool]
        """
        workspace_id = f"{env}-{region}-{deployment_code}-{sid}".upper()
        workspace_path = self.root_path / workspace_id

        if workspace_path.exists():
            metadata = WorkspaceMetadata.from_workspace_id(workspace_id, self.root_path)
            return (metadata, False)
        workspace_path.mkdir(parents=True, exist_ok=True)
        if template_dir and template_dir.exists():
            for item in template_dir.iterdir():
                if item.is_file():
                    shutil.copy2(item, workspace_path / item.name)
                elif item.is_dir() and not item.name.startswith("."):
                    shutil.copytree(item, workspace_path / item.name)
        else:
            (workspace_path / "logs").mkdir(exist_ok=True)
            (workspace_path / "offline_validation").mkdir(exist_ok=True)

        metadata = WorkspaceMetadata.from_workspace_id(workspace_id, self.root_path)
        return (metadata, True)

    def find_by_sid_env(self, sid: str, env: Optional[str] = None) -> list[WorkspaceMetadata]:
        """Find workspaces matching SID and optionally environment.

        :param sid: SAP System ID
        :type sid: str
        :param env: Environment (optional - if None, searches across all environments)
        :type env: Optional[str]
        :returns: List of matching workspace metadata
        :rtype: list[WorkspaceMetadata]
        """
        all_workspaces = self.list_workspaces()

        if env is None or env.strip() == "":
            return [ws for ws in all_workspaces if ws.sid.upper() == sid.upper()]
        else:
            return [
                ws
                for ws in all_workspaces
                if ws.sid.upper() == sid.upper() and ws.env.upper() == env.upper()
            ]
