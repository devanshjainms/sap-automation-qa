# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class HostInfo:
    """Host connection information for a SAP system node.

    IMPORTANT: All fields should be explicitly provided. No assumptions should be made.
    """

    hostname: str
    ip_address: str
    ansible_user: str
    connection_type: str
    virtual_host: str
    become_user: str
    vm_name: str
    node_tier: str

    def to_dict(self) -> dict:
        """Convert to dictionary for YAML serialization."""
        return {
            "ansible_host": self.ip_address,
            "ansible_user": self.ansible_user,
            "ansible_connection": "ssh",
            "connection_type": self.connection_type,
            "virtual_host": self.virtual_host,
            "become_user": self.become_user,
            "os_type": "linux",
            "vm_name": self.vm_name,
        }


@dataclass
class WorkspaceMetadata:
    """Metadata for a SAP QA workspace.

    Supports flexible workspace naming - can be just SID or full ENV-REGION-DEPLOYMENT-SID format.

    NOTE: Configuration fields (sap_sid, db_sid, etc.) are loaded from sap-parameters.yaml
    and should NOT have assumed defaults. Empty string indicates "not set".
    """

    workspace_id: str
    sid: str
    path: Path
    env: str = ""
    region: str = ""
    deployment_code: str = ""
    name: str = ""
    description: str = ""
    sap_sid: str = ""
    db_sid: str = ""
    platform: str = ""
    database_high_availability: bool = False
    scs_high_availability: bool = False
    database_cluster_type: str = ""
    scs_cluster_type: str = ""
    nfs_provider: str = ""
    db_instance_number: str = ""
    scs_instance_number: str = ""
    ers_instance_number: str = ""
    auth_type: str = ""
    key_vault_id: str = ""
    secret_id: str = ""
    user_assigned_identity_client_id: str = ""
    hosts: list = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert metadata to dictionary.

        :returns: Dictionary representation of workspace metadata
        :rtype: dict
        """
        return {
            "workspace_id": self.workspace_id,
            "name": self.name or self.workspace_id,
            "sid": self.sid,
            "env": self.env,
            "region": self.region,
            "deployment_code": self.deployment_code,
            "path": str(self.path),
            "description": self.description,
            "sap_sid": self.sap_sid or self.sid,
            "db_sid": self.db_sid,
            "platform": self.platform,
            "database_high_availability": self.database_high_availability,
            "scs_high_availability": self.scs_high_availability,
        }

    def to_summary_dict(self) -> dict:
        """Return minimal summary for listing."""
        return {
            "workspace_id": self.workspace_id,
            "name": self.name or self.workspace_id,
            "sid": self.sid,
            "env": self.env,
            "path": str(self.path),
        }

    @classmethod
    def from_workspace_id(cls, workspace_id: str, base_path: Path) -> Optional["WorkspaceMetadata"]:
        """Parse workspace metadata from workspace_id.

        Supports multiple formats:
        - Full: {ENV}-{REGION}-{DEPLOYMENT_CODE}-{SID} (e.g., DEV-WEEU-SAP01-X00)
        - Partial: {ENV}-{SID} (e.g., DEV-X00)
        - Simple: {SID} (e.g., X00, NW1)

        :param workspace_id: Workspace identifier
        :type workspace_id: str
        :param base_path: Base path to workspaces directory
        :type base_path: Path
        :returns: WorkspaceMetadata if valid, None otherwise
        :rtype: Optional[WorkspaceMetadata]
        """
        workspace_path = base_path / workspace_id
        parts = workspace_id.split("-")

        if len(parts) >= 4:
            env = parts[0]
            region = parts[1]
            sid = parts[-1]
            deployment_code = "-".join(parts[2:-1])
        elif len(parts) == 2:
            env = parts[0]
            region = ""
            deployment_code = ""
            sid = parts[1]
        elif len(parts) == 1:
            env = ""
            region = ""
            deployment_code = ""
            sid = parts[0]
        else:
            env = parts[0]
            region = parts[1]
            deployment_code = ""
            sid = parts[2]

        return cls(
            workspace_id=workspace_id,
            env=env,
            region=region,
            deployment_code=deployment_code,
            sid=sid,
            path=workspace_path,
            sap_sid=sid,
        )
