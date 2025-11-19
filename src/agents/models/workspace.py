# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class WorkspaceMetadata:
    """Metadata for a SAP QA workspace."""

    workspace_id: str
    env: str
    region: str
    deployment_code: str
    sid: str
    path: Path

    def to_dict(self) -> dict:
        """Convert metadata to dictionary.

        :returns: Dictionary representation of workspace metadata
        :rtype: dict
        """
        return {
            "workspace_id": self.workspace_id,
            "env": self.env,
            "region": self.region,
            "deployment_code": self.deployment_code,
            "sid": self.sid,
            "path": str(self.path),
        }

    @classmethod
    def from_workspace_id(cls, workspace_id: str, base_path: Path) -> Optional["WorkspaceMetadata"]:
        """Parse workspace metadata from workspace_id.

        Format: {ENV}-{REGION}-{DEPLOYMENT_CODE}-{SID}
        Example: DEV-WEEU-SAP01-X00

        :param workspace_id: Workspace identifier
        :type workspace_id: str
        :param base_path: Base path to workspaces directory
        :type base_path: Path
        :returns: WorkspaceMetadata if valid format, None otherwise
        :rtype: Optional[WorkspaceMetadata]
        """
        parts = workspace_id.split("-")
        if len(parts) < 4:
            return None

        env = parts[0]
        region = parts[1]
        sid = parts[-1]
        deployment_code = "-".join(parts[2:-1])

        workspace_path = base_path / workspace_id

        return cls(
            workspace_id=workspace_id,
            env=env,
            region=region,
            deployment_code=deployment_code,
            sid=sid,
            path=workspace_path,
        )
