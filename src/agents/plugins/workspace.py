# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Lean workspace plugin - tools for the LLM, not business logic.

Philosophy: Provide simple read/write tools + examples. Let LLM reason about
structure, validation, and workflow. Don't encode business rules in code.
"""

import yaml
import json
from pathlib import Path
from typing import Annotated

from semantic_kernel.functions import kernel_function

from src.agents.workspace.workspace_store import WorkspaceStore
from src.agents.observability import get_logger
from src.agents.workspace_cache import WorkspaceCacheManager

logger = get_logger(__name__)


class WorkspacePlugin:
    """Lean workspace plugin - simple tools, LLM does the thinking."""

    def __init__(self, store: WorkspaceStore) -> None:
        self.store = store
        logger.info(f"WorkspacePlugin initialized: {store.root_path}")

    @kernel_function(
        name="list_workspaces",
        description="List all workspace names/IDs in the system.",
    )
    def list_workspaces(self) -> str:
        """List all workspaces."""
        workspaces = self.store.list_workspace_ids()
        return json.dumps({"workspaces": workspaces, "count": len(workspaces)})

    @kernel_function(
        name="workspace_exists",
        description="Check if a workspace exists.",
    )
    def workspace_exists(self, workspace_id: Annotated[str, "Workspace name/ID to check"]) -> str:
        """Check if workspace exists."""
        exists = self.store.workspace_exists(workspace_id)
        return json.dumps({"workspace_id": workspace_id, "exists": exists})

    @kernel_function(
        name="list_workspace_files",
        description="List all files in a workspace directory.",
    )
    def list_workspace_files(self, workspace_id: Annotated[str, "Workspace name/ID"]) -> str:
        """List files in workspace."""
        files = self.store.list_files(workspace_id)
        return json.dumps({"workspace_id": workspace_id, "files": files})

    @kernel_function(
        name="get_workspace_file_path",
        description="Get the absolute filesystem path for a file inside a workspace. "
        "Use this after list_workspace_files to pass a real path to SSH/Ansible.",
    )
    def get_workspace_file_path(
        self,
        workspace_id: Annotated[str, "Workspace name/ID"],
        filename: Annotated[str, "Workspace filename (must be a single file name, not a path)"],
    ) -> str:
        """Resolve a workspace file to an absolute path.

        This intentionally only accepts a single filename (no subdirectories) to
        avoid path traversal and to keep the tool behavior predictable for the LLM.
        """
        if not filename or filename.strip() == "":
            return json.dumps({"error": "filename is required", "workspace_id": workspace_id})

        candidate = Path(filename)
        if (
            candidate.name != filename
            or ".." in candidate.parts
            or "/" in filename
            or "\\" in filename
        ):
            return json.dumps(
                {
                    "error": "Invalid filename. Provide a single file name (no directories).",
                    "workspace_id": workspace_id,
                    "filename": filename,
                }
            )

        workspace_path = self.store.get_workspace_path(workspace_id)
        file_path = (workspace_path / filename).resolve()

        if not workspace_path.exists():
            return json.dumps(
                {"error": f"Workspace not found: {workspace_id}", "workspace_id": workspace_id}
            )

        try:
            file_path.relative_to(workspace_path.resolve())
        except ValueError:
            return json.dumps(
                {
                    "error": "Resolved path is outside workspace (blocked)",
                    "workspace_id": workspace_id,
                    "filename": filename,
                }
            )

        if not file_path.exists():
            return json.dumps(
                {
                    "error": f"File not found: {filename}",
                    "workspace_id": workspace_id,
                    "filename": filename,
                    "path": str(file_path),
                }
            )

        return json.dumps(
            {
                "workspace_id": workspace_id,
                "filename": filename,
                "path": str(file_path),
            }
        )

    @kernel_function(
        name="read_workspace_file",
        description="Read any file from a workspace. Use this to see examples of hosts.yaml, "
        "sap-parameters.yaml, or any other configuration file.",
    )
    def read_workspace_file(
        self,
        workspace_id: Annotated[str, "Workspace name/ID"],
        filename: Annotated[str, "File to read (e.g., hosts.yaml, sap-parameters.yaml)"],
    ) -> str:
        """Read a file from workspace."""
        content = self.store.read_file(workspace_id, filename)
        if content is None:
            return json.dumps(
                {
                    "error": f"File not found: {filename}",
                    "workspace_id": workspace_id,
                }
            )
        return json.dumps(
            {
                "workspace_id": workspace_id,
                "filename": filename,
                "content": content,
            }
        )

    @kernel_function(
        name="get_example_hosts_yaml",
        description="Get an example hosts.yaml from an existing workspace. "
        "Use this to understand the required format before creating a new one.",
    )
    def get_example_hosts_yaml(self) -> str:
        """Find and return an example hosts.yaml."""
        workspace_ids = self.store.list_workspace_ids()
        for ws_id in workspace_ids:
            content = self.store.read_file(ws_id, "hosts.yaml")
            if content:
                return json.dumps(
                    {
                        "example_from": ws_id,
                        "filename": "hosts.yaml",
                        "content": content,
                        "note": "Use this as a template. Replace values with user's actual data.",
                    }
                )
        return json.dumps(
            {
                "error": "No example hosts.yaml found in any workspace",
                "suggestion": "Ask user for host details and create from scratch",
            }
        )

    @kernel_function(
        name="get_example_sap_parameters",
        description="Get an example sap-parameters.yaml from an existing workspace.",
    )
    def get_example_sap_parameters(self) -> str:
        """Find and return an example sap-parameters.yaml."""
        workspace_ids = self.store.list_workspace_ids()
        for ws_id in workspace_ids:
            content = self.store.read_file(ws_id, "sap-parameters.yaml")
            if content:
                return json.dumps(
                    {
                        "example_from": ws_id,
                        "filename": "sap-parameters.yaml",
                        "content": content,
                    }
                )
        return json.dumps({"error": "No example sap-parameters.yaml found"})

    @kernel_function(
        name="get_system_configuration",
        description=(
            "Read sap-parameters.yaml and hosts.yaml for a workspace and return a structured "
            "JSON with platform, HA flags, hosts list, and source file paths."
        ),
    )
    def get_system_configuration(self, workspace_id: Annotated[str, "Workspace name/ID"]) -> str:
        """Return system configuration for a workspace as JSON string.

        This function reads 'sap-parameters.yaml' and 'hosts.yaml' if present.
        """
        import yaml

        result = {
            "workspace_id": workspace_id,
            "platform": None,
            "database_high_availability": None,
            "scs_high_availability": None,
            "hosts": [],
            "sources": [],
        }

        # Read sap-parameters.yaml
        sap_params = self.store.read_file(workspace_id, "sap-parameters.yaml")
        if sap_params:
            try:
                parsed = yaml.safe_load(sap_params)
                result["platform"] = parsed.get("platform") if isinstance(parsed, dict) else None
                result["database_high_availability"] = (
                    parsed.get("database_high_availability") if isinstance(parsed, dict) else None
                )
                result["scs_high_availability"] = (
                    parsed.get("scs_high_availability") if isinstance(parsed, dict) else None
                )
                result["sources"].append(
                    {
                        "file": "sap-parameters.yaml",
                        "path": str(
                            self.store.get_workspace_path(workspace_id) / "sap-parameters.yaml"
                        ),
                    }
                )
            except Exception:
                result["sources"].append({"file": "sap-parameters.yaml", "error": "parse_error"})

        # Read hosts.yaml
        hosts_raw = self.store.read_file(workspace_id, "hosts.yaml")
        if hosts_raw:
            try:
                hosts_parsed = yaml.safe_load(hosts_raw)
                # Expecting host groups or list
                result["hosts"] = hosts_parsed if hosts_parsed else []
                result["sources"].append(
                    {
                        "file": "hosts.yaml",
                        "path": str(self.store.get_workspace_path(workspace_id) / "hosts.yaml"),
                    }
                )
            except Exception:
                result["sources"].append({"file": "hosts.yaml", "error": "parse_error"})

        return json.dumps(result)

    @kernel_function(
        name="create_workspace",
        description="Create a new workspace directory. Just creates the folder.",
    )
    def create_workspace(self, workspace_id: Annotated[str, "Name for the new workspace"]) -> str:
        """Create workspace directory."""
        if self.store.workspace_exists(workspace_id):
            return json.dumps(
                {
                    "workspace_id": workspace_id,
                    "created": False,
                    "message": "Workspace already exists",
                }
            )
        path = self.store.create_workspace_dir(workspace_id)
        return json.dumps(
            {
                "workspace_id": workspace_id,
                "created": True,
                "path": str(path),
            }
        )

    @kernel_function(
        name="write_workspace_file",
        description="Write content to a file in a workspace. Creates workspace if needed. "
        "Use this to write hosts.yaml, sap-parameters.yaml, or any config file.",
    )
    def write_workspace_file(
        self,
        workspace_id: Annotated[str, "Workspace name/ID"],
        filename: Annotated[str, "Filename to write (e.g., hosts.yaml)"],
        content: Annotated[str, "File content to write"],
    ) -> str:
        """Write file to workspace."""
        path = self.store.write_file(workspace_id, filename, content)
        return json.dumps(
            {
                "workspace_id": workspace_id,
                "filename": filename,
                "written": True,
                "path": path,
            }
        )

    @kernel_function(
        name="get_workspace_status",
        description="Check what files exist in a workspace and if it's ready for testing.",
    )
    def get_workspace_status(self, workspace_id: Annotated[str, "Workspace name/ID"]) -> str:
        """Get workspace status - what files exist."""
        if not self.store.workspace_exists(workspace_id):
            return json.dumps({"error": "Workspace not found", "workspace_id": workspace_id})

        files = self.store.list_files(workspace_id)
        path = self.store.get_workspace_path(workspace_id)

        has_hosts = "hosts.yaml" in files
        has_params = "sap-parameters.yaml" in files
        has_key = "ssh_key.ppk" in files or any("key" in f.lower() for f in files)

        return json.dumps(
            {
                "workspace_id": workspace_id,
                "path": str(path),
                "files": files,
                "has_hosts_yaml": has_hosts,
                "has_sap_parameters": has_params,
                "has_credentials": has_key,
                "ready_for_testing": has_hosts and has_params,
            }
        )

    @kernel_function(
        name="resolve_ssh_key",
        description="Find the SSH key for a workspace. Checks: 1) Local files (.pem, .ppk), "
        "2) Returns the absolute path to the key file. Use this before any SSH operation.",
    )
    def resolve_ssh_key(self, workspace_id: Annotated[str, "Workspace name/ID"]) -> str:
        """Find SSH key for a workspace - single source of truth for SSH key discovery.

        Priority:
        1. Look for key files in workspace (.pem, .ppk, ssh_key*, id_rsa*)
        2. Return error if no key found
        """
        if not self.store.workspace_exists(workspace_id):
            return json.dumps({"error": "Workspace not found", "workspace_id": workspace_id})

        workspace_path = self.store.get_workspace_path(workspace_id)
        files = self.store.list_files(workspace_id)
        key_patterns = [".pem", ".ppk", "ssh_key", "id_rsa", "_key"]
        for filename in files:
            filename_lower = filename.lower()
            if any(pattern in filename_lower for pattern in key_patterns):
                if not filename.endswith(".pub"):  # Skip public keys
                    key_path = workspace_path / filename
                    if key_path.exists():
                        logger.info(f"Resolved SSH key: {key_path}")
                        return json.dumps(
                            {
                                "workspace_id": workspace_id,
                                "key_path": str(key_path),
                                "key_file": filename,
                                "found": True,
                            }
                        )

        return json.dumps(
            {
                "workspace_id": workspace_id,
                "found": False,
                "error": "No SSH key file found in workspace",
                "hint": "Add an SSH key file (.pem or .ppk) to the workspace directory",
                "files_checked": files,
            }
        )

    @kernel_function(
        name="get_execution_context",
        description="Get complete execution context for a workspace (hosts, parameters, SSH key, "
        "inventory path). Returns all data needed for test execution or command runs. "
        "Call this once before any execution - no need to resolve SSH keys separately.",
    )
    def get_execution_context(self, workspace_id: Annotated[str, "Workspace name/ID"]) -> str:
        """Get complete execution context for a workspace - SINGLE SOURCE OF TRUTH.

        Returns all data needed by ExecutionPlugin:
        - inventory_path: Path to hosts.yaml for Ansible
        - sap_parameters: Parsed sap-parameters.yaml as dict (for extra_vars)
        - ssh_key_path: Resolved SSH key path (or null if not found)
        - hosts: Parsed hosts.yaml content
        - workspace_path: Absolute path to workspace directory

        Uses WorkspaceCache to avoid repeated file reads within the same conversation.
        """
        cache = WorkspaceCacheManager.get()
        if cache and not cache.is_expired():
            cached_context = cache.get_execution_context()
            if cached_context and cached_context.get("workspace_id") == workspace_id:
                logger.info(f"✓ Using cached execution context for {workspace_id}")
                return json.dumps(cached_context, indent=2)

        if not self.store.workspace_exists(workspace_id):
            return json.dumps({"error": "Workspace not found", "workspace_id": workspace_id})

        workspace_path = self.store.get_workspace_path(workspace_id)
        files = self.store.list_files(workspace_id)

        result = {
            "workspace_id": workspace_id,
            "workspace_path": str(workspace_path),
            "inventory_path": None,
            "hosts": None,
            "sap_parameters": {},
            "ssh_key_path": None,
            "ssh_key_file": None,
            "ready": False,
            "missing": [],
        }
        hosts_path = workspace_path / "hosts.yaml"
        if hosts_path.exists():
            result["inventory_path"] = str(hosts_path)
            try:
                hosts_content = self.store.read_file(workspace_id, "hosts.yaml")
                result["hosts"] = yaml.safe_load(hosts_content) if hosts_content else None
            except Exception as e:
                logger.warning(f"Failed to parse hosts.yaml: {e}")
                result["hosts"] = None
        else:
            result["missing"].append("hosts.yaml")
        params_content = self.store.read_file(workspace_id, "sap-parameters.yaml")
        if params_content:
            try:
                result["sap_parameters"] = yaml.safe_load(params_content) or {}
            except Exception as e:
                logger.warning(f"Failed to parse sap-parameters.yaml: {e}")
                result["sap_parameters"] = {}
        else:
            result["missing"].append("sap-parameters.yaml")
        key_patterns = [".pem", ".ppk", "ssh_key", "id_rsa", "_key"]
        for filename in files:
            filename_lower = filename.lower()
            if any(pattern in filename_lower for pattern in key_patterns):
                if not filename.endswith(".pub"):
                    key_path = workspace_path / filename
                    if key_path.exists():
                        result["ssh_key_path"] = str(key_path)
                        result["ssh_key_file"] = filename
                        logger.info(f"Resolved SSH key from workspace: {key_path}")
                        break
        if not result["ssh_key_path"]:
            temp_key_dir = Path("/tmp/sap_keys")
            for key_name in [f"{workspace_id}_id_rsa", "id_rsa"]:
                temp_key_path = temp_key_dir / key_name
                if temp_key_path.exists():
                    result["ssh_key_path"] = str(temp_key_path)
                    result["ssh_key_file"] = temp_key_path.name
                    logger.info(f"Resolved SSH key from KeyVault temp: {temp_key_path}")
                    break

        if not result["ssh_key_path"]:
            result["missing"].append("ssh_key")
        result["ready"] = (
            result["inventory_path"] is not None and result["ssh_key_path"] is not None
        )

        logger.info(
            f"Execution context for {workspace_id}: ready={result['ready']}, "
            f"missing={result['missing']}"
        )

        if cache:
            cache.set_execution_context(result)

        return json.dumps(result, indent=2)
