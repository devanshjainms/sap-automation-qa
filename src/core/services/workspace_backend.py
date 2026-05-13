# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Workspace storage backends — filesystem and Azure Blob Storage.

* :class:`FilesystemBackend` — reads from a local directory (default).
* :class:`BlobBackend` — reads from Azure Blob Storage via managed identity.
"""

from __future__ import annotations
import logging
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol
import yaml
from azure.identity import DefaultAzureCredential
from azure.storage.blob import ContainerClient
from src.core.models.workspace import WorkspaceInfo

logger = logging.getLogger(__name__)


class WorkspaceBackend(Protocol):
    """Protocol for workspace storage backends.

    All workspace I/O (listing, file reads, YAML parsing) flows through
    this interface so that callers are decoupled from the storage medium.
    """

    def list_workspaces(self) -> List[WorkspaceInfo]:
        """List all available workspaces.

        :returns: Discovered workspaces with metadata.
        :rtype: List[WorkspaceInfo]
        """
        ...

    def read_file(self, workspace_id: str, filename: str) -> Optional[str]:
        """Read a file from a workspace.

        :param workspace_id: Workspace directory name or blob prefix.
        :param filename: File name relative to the workspace root.
        :returns: File content as a string, or ``None`` if not found.
        :rtype: Optional[str]
        """
        ...

    def read_yaml(self, workspace_id: str, filename: str) -> Dict[str, Any]:
        """Read and parse a YAML file from a workspace.

        :param workspace_id: Workspace directory name or blob prefix.
        :param filename: YAML file name relative to workspace root.
        :returns: Parsed YAML as a dict, or empty dict if not found.
        :rtype: Dict[str, Any]
        """
        ...

    def file_exists(self, workspace_id: str, filename: str) -> bool:
        """Check whether a file exists in a workspace.

        :param workspace_id: Workspace directory name or blob prefix.
        :param filename: File name relative to the workspace root.
        :returns: ``True`` if the file exists.
        :rtype: bool
        """
        ...

    def workspace_path(self, workspace_id: str) -> str:
        """Return the canonical path or URI for a workspace.

        For filesystem backends this is the local directory path.
        For blob backends this is the container URL prefix.

        :param workspace_id: Workspace directory name or blob prefix.
        :returns: Canonical location string.
        :rtype: str
        """
        ...


class FilesystemBackend:
    """Local filesystem workspace backend (default).

    Reads workspace configuration files from a directory tree where
    each subdirectory is a workspace containing ``hosts.yaml`` and/or
    ``sap-parameters.yaml``.

    :param base_dir: Root directory containing workspace subdirectories.
    :type base_dir: str
    """

    def __init__(self, base_dir: str = "WORKSPACES/SYSTEM") -> None:
        self._base = Path(base_dir)

    def list_workspaces(self) -> List[WorkspaceInfo]:
        """List workspaces by scanning subdirectories.

        :returns: Discovered workspaces with metadata.
        :rtype: List[WorkspaceInfo]
        """
        workspaces: List[WorkspaceInfo] = []

        if not self._base.exists():
            logger.warning("Workspaces directory not found: %s", self._base)
            return workspaces

        for workspace_dir in self._base.iterdir():
            if not workspace_dir.is_dir() or workspace_dir.name.startswith("."):
                continue

            has_hosts = (workspace_dir / "hosts.yaml").exists()
            has_params = (workspace_dir / "sap-parameters.yaml").exists()

            if not has_hosts and not has_params:
                continue

            sap_sid = ""
            if has_params:
                try:
                    with open(
                        workspace_dir / "sap-parameters.yaml",
                        encoding="utf-8",
                    ) as fh:
                        params = yaml.safe_load(fh) or {}
                    sap_sid = params.get("sap_sid", "")
                except Exception as exc:
                    logger.warning(
                        "Failed to load sap-parameters for %s: %s",
                        workspace_dir.name,
                        exc,
                    )

            ws_name = workspace_dir.name
            workspaces.append(
                WorkspaceInfo(
                    id=ws_name,
                    name=sap_sid or ws_name,
                    environment=(ws_name.split("-")[0] if "-" in ws_name else ""),
                    path=str(workspace_dir),
                    config_exists=has_params,
                )
            )

        return workspaces

    def read_file(self, workspace_id: str, filename: str) -> Optional[str]:
        """Read a file from a workspace directory.

        :param workspace_id: Workspace directory name.
        :param filename: File name relative to the workspace root.
        :returns: File content, or ``None`` if not found.
        :rtype: Optional[str]
        """
        path = self._base / workspace_id / filename
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    def read_yaml(self, workspace_id: str, filename: str) -> Dict[str, Any]:
        """Read and parse a YAML file from a workspace directory.

        :param workspace_id: Workspace directory name.
        :param filename: YAML file name relative to workspace root.
        :returns: Parsed YAML as a dict, or empty dict if missing.
        :rtype: Dict[str, Any]
        """
        content = self.read_file(workspace_id, filename)
        if content is None:
            return {}
        return yaml.safe_load(content) or {}

    def file_exists(self, workspace_id: str, filename: str) -> bool:
        """Check whether a file exists in a workspace directory.

        :param workspace_id: Workspace directory name.
        :param filename: File name relative to the workspace root.
        :returns: ``True`` if the file exists and is a regular file.
        :rtype: bool
        """
        return (self._base / workspace_id / filename).is_file()

    def workspace_path(self, workspace_id: str) -> str:
        """Return the local filesystem path for a workspace.

        :param workspace_id: Workspace directory name.
        :returns: Absolute or relative path to the workspace directory.
        :rtype: str
        """
        return str(self._base / workspace_id)


class BlobBackend:
    """
    Azure Blob Storage workspace backend using managed identity.

    :param account_url: Blob account URL,
        e.g. ``https://stafworkspaces.blob.core.windows.net``.
    :type account_url: str
    :param container_name: Container name holding workspace blobs.
    :type container_name: str
    """

    def __init__(
        self,
        account_url: str,
        container_name: str = "workspaces",
    ) -> None:
        self._credential = DefaultAzureCredential()
        self._client = ContainerClient(
            account_url=account_url,
            container_name=container_name,
            credential=self._credential,
        )
        self._container_name = container_name
        self._account_url = account_url

    def list_workspaces(self) -> List[WorkspaceInfo]:
        """List workspaces by discovering blob prefixes.

        Scans all blobs in the container and identifies unique
        top-level prefixes that contain ``hosts.yaml`` and/or
        ``sap-parameters.yaml``.

        :returns: Discovered workspaces with metadata.
        :rtype: List[WorkspaceInfo]
        """
        seen: dict[str, dict[str, bool]] = {}

        for blob in self._client.list_blobs():
            parts = blob.name.split("/", 1)
            if len(parts) < 2:
                continue
            ws_id = parts[0]
            filename = parts[1]
            if ws_id.startswith("."):
                continue
            if ws_id not in seen:
                seen[ws_id] = {
                    "has_hosts": False,
                    "has_params": False,
                }
            if filename == "hosts.yaml":
                seen[ws_id]["has_hosts"] = True
            if filename == "sap-parameters.yaml":
                seen[ws_id]["has_params"] = True

        workspaces: List[WorkspaceInfo] = []
        for ws_id, files in seen.items():
            if not files["has_hosts"] and not files["has_params"]:
                continue
            sap_sid = ""
            if files["has_params"]:
                params = self.read_yaml(ws_id, "sap-parameters.yaml")
                sap_sid = params.get("sap_sid", "")
            workspaces.append(
                WorkspaceInfo(
                    id=ws_id,
                    name=sap_sid or ws_id,
                    environment=(ws_id.split("-")[0] if "-" in ws_id else ""),
                    path=(f"{self._account_url}/" f"{self._container_name}/{ws_id}"),
                    config_exists=files["has_params"],
                )
            )
        return workspaces

    def read_file(self, workspace_id: str, filename: str) -> Optional[str]:
        """Read a blob from a workspace prefix.

        :param workspace_id: Top-level blob prefix (workspace ID).
        :param filename: Blob name relative to the workspace prefix.
        :returns: Blob content as a UTF-8 string, or ``None`` on error.
        :rtype: Optional[str]
        """
        blob_name = f"{workspace_id}/{filename}"
        try:
            blob_client = self._client.get_blob_client(blob_name)
            return blob_client.download_blob().readall().decode("utf-8")
        except Exception:
            logger.debug("Blob not found or unreadable: %s", blob_name)
            return None

    def read_yaml(self, workspace_id: str, filename: str) -> Dict[str, Any]:
        """Read and parse a YAML blob from a workspace prefix.

        :param workspace_id: Top-level blob prefix (workspace ID).
        :param filename: YAML blob name relative to workspace prefix.
        :returns: Parsed YAML as a dict, or empty dict on failure.
        :rtype: Dict[str, Any]
        """
        content = self.read_file(workspace_id, filename)
        if content is None:
            return {}
        return yaml.safe_load(content) or {}

    def file_exists(self, workspace_id: str, filename: str) -> bool:
        """Check whether a blob exists in a workspace prefix.

        :param workspace_id: Top-level blob prefix (workspace ID).
        :param filename: Blob name relative to the workspace prefix.
        :returns: ``True`` if the blob exists.
        :rtype: bool
        """
        blob_name = f"{workspace_id}/{filename}"
        blob_client = self._client.get_blob_client(blob_name)
        try:
            blob_client.get_blob_properties()
            return True
        except Exception:
            return False

    def workspace_path(self, workspace_id: str) -> str:
        """Return the blob container URL for a workspace prefix.

        :param workspace_id: Top-level blob prefix (workspace ID).
        :returns: Full URL to the workspace prefix in blob storage.
        :rtype: str
        """
        return f"{self._account_url}/" f"{self._container_name}/{workspace_id}"


def create_workspace_backend() -> WorkspaceBackend:
    """
    Factory — create the appropriate backend from environment.
    When ``BLOB_ACCOUNT_URL`` is set, uses Azure Blob Storage with
    managed identity.  Otherwise, falls back to the local filesystem.

    :returns: A backend satisfying :class:`WorkspaceBackend`.
    :rtype: WorkspaceBackend
    """
    account_url = os.environ.get("BLOB_ACCOUNT_URL", "")

    if account_url:
        container_name = os.environ.get("BLOB_CONTAINER_NAME", "workspaces")
        logger.info(
            "Workspace backend: Azure Blob Storage (%s/%s)",
            account_url,
            container_name,
        )
        return BlobBackend(
            account_url=account_url,
            container_name=container_name,
        )

    base_dir = os.environ.get("WORKSPACES_BASE", "WORKSPACES/SYSTEM")
    logger.info("Workspace backend: filesystem (%s)", base_dir)
    return FilesystemBackend(base_dir=base_dir)


def create_workspace_config_loader(
    backend_factory: Callable[[], "WorkspaceBackend"],
) -> Callable[[str], Dict[str, Any]]:
    """Create a workspace config loader that uses the active backend.

    For filesystem backends the inventory path points directly at the
    local ``hosts.yaml``.  For blob backends the files are downloaded
    to a temporary directory so that Ansible can read them.

    :param backend_factory: Callable returning the workspace backend.
    :returns: A loader function ``(workspace_id) -> config dict``.
    :rtype: Callable[[str], Dict[str, Any]]
    """

    def loader(workspace_id: str) -> Dict[str, Any]:
        backend = backend_factory()

        hosts_content = backend.read_file(workspace_id, "hosts.yaml")
        if hosts_content is None:
            return {}

        params = backend.read_yaml(workspace_id, "sap-parameters.yaml")

        if isinstance(backend, FilesystemBackend):
            inventory_path = str(backend._base / workspace_id / "hosts.yaml")
            cleanup_path = ""
        else:
            temp_dir = Path(tempfile.mkdtemp(prefix=f"staf-ws-{workspace_id}-"))
            (temp_dir / "hosts.yaml").write_text(hosts_content, encoding="utf-8")
            params_content = backend.read_file(workspace_id, "sap-parameters.yaml")
            if params_content:
                (temp_dir / "sap-parameters.yaml").write_text(params_content, encoding="utf-8")
            inventory_path = str(temp_dir / "hosts.yaml")
            cleanup_path = str(temp_dir)

        config: Dict[str, Any] = {"inventory_path": inventory_path}
        if cleanup_path:
            config["_cleanup_path"] = cleanup_path
        config["sap_sid"] = params.get("sap_sid", "")
        config["db_sid"] = params.get("db_sid", "")
        config["database_high_availability"] = params.get("database_high_availability", False)
        config["scs_high_availability"] = params.get("scs_high_availability", False)
        config["extra_vars"] = params

        return config

    return loader
