# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Workspace models."""

from typing import List, Any
from pydantic import BaseModel


class WorkspaceInfo(BaseModel):
    """Workspace information."""

    id: str
    name: str
    environment: str = ""
    path: str = ""
    config_exists: bool = False


class WorkspaceConfig(BaseModel):
    """Whitelisted workspace configuration fields safe for UI display."""

    sap_sid: str = ""
    db_sid: str = ""
    platform: str = ""
    db_instance_number: str = ""
    scs_instance_number: str = ""
    ers_instance_number: str = ""
    database_high_availability: bool = False
    scs_high_availability: bool = False
    database_cluster_type: str = ""
    scs_cluster_type: str = ""
    database_scale_out: bool = False
    nfs_provider: str = ""
    hosts: List[str] = []


class TestReport(BaseModel):
    """Metadata for an HTML test report file."""

    filename: str
    modified_at: str
    size_bytes: int


class WorkspaceListResponse(BaseModel):
    """Response containing list of workspaces."""

    workspaces: List[WorkspaceInfo]
    total: int
