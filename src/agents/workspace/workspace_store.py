# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Lean workspace store - file operations + minimal backward compatibility.
"""

from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import threading

from src.agents.models.workspace import WorkspaceMetadata


class WorkspaceStore:
    """Simple file-based workspace store with baseline health caching."""

    def __init__(self, root_path: str | Path, baseline_ttl_seconds: int = 300) -> None:
        self.root_path = Path(root_path)
        self.root_path.mkdir(parents=True, exist_ok=True)
        self._baseline_cache: Dict[str, Dict[str, Any]] = {}
        self._baseline_ttl = timedelta(seconds=baseline_ttl_seconds)
        self._cache_lock = threading.RLock()

    def list_workspace_ids(self) -> list[str]:
        """List all workspace directory names."""
        if not self.root_path.exists():
            return []
        return [
            item.name
            for item in self.root_path.iterdir()
            if item.is_dir() and not item.name.startswith(".")
        ]

    def workspace_exists(self, workspace_id: str) -> bool:
        """Check if workspace directory exists."""
        return (self.root_path / workspace_id).is_dir()

    def get_workspace_path(self, workspace_id: str) -> Path:
        """Get path to workspace directory."""
        return self.root_path / workspace_id

    def create_workspace_dir(self, workspace_id: str) -> Path:
        """Create workspace directory. Returns path."""
        path = self.root_path / workspace_id.upper()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def read_file(self, workspace_id: str, filename: str) -> Optional[str]:
        """Read a file from workspace. Returns content or None."""
        file_path = self.root_path / workspace_id / filename
        if file_path.exists():
            return file_path.read_text()
        return None

    def write_file(self, workspace_id: str, filename: str, content: str) -> str:
        """Write content to a file in workspace. Creates workspace if needed."""
        workspace_path = self.root_path / workspace_id
        workspace_path.mkdir(parents=True, exist_ok=True)
        file_path = workspace_path / filename
        file_path.write_text(content)
        return str(file_path)

    def list_files(self, workspace_id: str) -> list[str]:
        """List files in a workspace."""
        workspace_path = self.root_path / workspace_id
        if not workspace_path.exists():
            return []
        return [f.name for f in workspace_path.iterdir() if f.is_file()]

    def list_workspaces(self) -> list[WorkspaceMetadata]:
        """List all workspaces as metadata objects (backward compat)."""
        workspaces = []
        for ws_id in self.list_workspace_ids():
            metadata = WorkspaceMetadata.from_workspace_id(ws_id, self.root_path)
            if metadata:
                workspaces.append(metadata)
        return workspaces

    def get_workspace(self, workspace_id: str) -> Optional[WorkspaceMetadata]:
        """Get workspace metadata by ID (backward compat)."""
        if not self.workspace_exists(workspace_id):
            return None
        return WorkspaceMetadata.from_workspace_id(workspace_id, self.root_path)

    def create_workspace(
        self,
        workspace_id: str = "",
        sid: str = "",
        env: str = "",
        region: str = "",
        deployment_code: str = "",
        template_dir: Optional[Path] = None,
    ) -> tuple[WorkspaceMetadata, bool]:
        """Create workspace (backward compat)."""
        if workspace_id:
            final_id = workspace_id.upper()
        elif sid:
            components = [c for c in [env, region, deployment_code, sid] if c]
            final_id = "-".join(components).upper()
        else:
            raise ValueError("Either workspace_id or sid must be provided")

        workspace_path = self.root_path / final_id
        is_new = not workspace_path.exists()

        workspace_path.mkdir(parents=True, exist_ok=True)
        (workspace_path / "logs").mkdir(exist_ok=True)

        metadata = WorkspaceMetadata.from_workspace_id(final_id, self.root_path)
        if metadata is None:
            raise ValueError(f"Invalid workspace_id format: {final_id}")

        return (metadata, is_new)

    def find_by_sid_env(self, sid: str, env: Optional[str] = None) -> list[WorkspaceMetadata]:
        """Find workspaces matching SID and optionally environment."""
        all_workspaces = self.list_workspaces()

        if env is None or env.strip() == "":
            return [ws for ws in all_workspaces if ws.sid.upper() == sid.upper()]
        return [
            ws
            for ws in all_workspaces
            if ws.sid.upper() == sid.upper() and ws.env.upper() == env.upper()
        ]

    def find_by_name_or_sid(self, query: str) -> list[WorkspaceMetadata]:
        """Find workspaces matching a name or SID query."""
        all_workspaces = self.list_workspaces()
        query_upper = query.upper()
        return [
            ws
            for ws in all_workspaces
            if query_upper in ws.workspace_id.upper() or query_upper in ws.sid.upper()
        ]

    def find_workspaces_by_sid(self, sid: str) -> list[str]:
        """Return workspace IDs that match the provided SID."""
        matches = self.find_by_sid_env(sid)
        return [ws.workspace_id for ws in matches]

    def get_baseline_cache(self, workspace_id: str) -> Optional[Dict[str, Any]]:
        """Get cached baseline results for a workspace."""
        with self._cache_lock:
            if workspace_id not in self._baseline_cache:
                return None

            cached = self._baseline_cache[workspace_id]
            age = datetime.utcnow() - cached["timestamp"]

            if age > self._baseline_ttl:
                del self._baseline_cache[workspace_id]
                return None

            return {
                "data": cached["results"],
                "age_seconds": int(age.total_seconds()),
                "check_tags": cached["check_tags"],
                "cached_at": cached["timestamp"].isoformat(),
            }

    def set_baseline_cache(
        self, workspace_id: str, results: Dict[str, Any], check_tags: list[str]
    ) -> None:
        """Cache baseline results for a workspace."""
        with self._cache_lock:
            self._baseline_cache[workspace_id] = {
                "workspace_id": workspace_id,
                "timestamp": datetime.utcnow(),
                "results": results,
                "check_tags": check_tags,
            }

    def invalidate_baseline_cache(self, workspace_id: str) -> None:
        """Invalidate cached baseline for a workspace."""
        with self._cache_lock:
            if workspace_id in self._baseline_cache:
                del self._baseline_cache[workspace_id]

    def clear_all_baseline_cache(self) -> None:
        """Clear all cached baselines."""
        with self._cache_lock:
            self._baseline_cache.clear()
