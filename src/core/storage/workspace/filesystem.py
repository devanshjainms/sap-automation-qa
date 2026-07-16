# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Filesystem-based workspace backend implementation."""

from __future__ import annotations
import shutil
from pathlib import Path
from typing import Any
from uuid import UUID
from src.core.exceptions import (
    WorkspaceConfigError,
    WorkspaceNotFoundError,
    WorkspaceValidationError,
)
from src.core.models.workspace import MaterializedWorkspace, WorkspaceConfig, WorkspaceSummary
from src.core.observability import get_logger
from src.core.storage.workspace.validation import (
    MAX_CONFIG_FILE_SIZE,
    extract_environment,
    parse_hosts_yaml,
    parse_sap_parameters,
    validate_workspace_id,
)

logger = get_logger(__name__)


class FilesystemWorkspaceBackend:
    """Filesystem-based workspace backend."""

    def __init__(self, workspaces_base: Path, data_dir: Path | None = None) -> None:
        self._base = workspaces_base
        self._data_dir = data_dir or Path("data")

    @property
    def backend_name(self) -> str:
        """Return ``"filesystem"``."""
        return "filesystem"

    def list_workspaces(self) -> list[WorkspaceSummary]:
        """List workspaces from the filesystem directory."""
        workspaces: list[WorkspaceSummary] = []
        if not self._base.exists():
            return workspaces

        base_resolved = self._base.resolve(strict=True)
        seen_lower: dict[str, str] = {}

        for entry in sorted(self._base.iterdir()):
            if entry.name.startswith("."):
                continue

            try:
                resolved_entry = self._resolve_within_base(entry, base_resolved)
            except (WorkspaceValidationError, FileNotFoundError):
                continue

            if not resolved_entry.is_dir():
                continue

            lower_name = entry.name.lower()
            if lower_name in seen_lower:
                logger.warning(
                    "Case collision: %s vs %s — skipping both",
                    entry.name,
                    seen_lower[lower_name],
                )
                workspaces = [w for w in workspaces if w.workspace_id != seen_lower[lower_name]]
                continue
            seen_lower[lower_name] = entry.name

            hosts_file = resolved_entry / "hosts.yaml"
            params_file = resolved_entry / "sap-parameters.yaml"
            if not hosts_file.exists() or not params_file.exists():
                continue

            try:
                hosts_content = self._read_required_file(hosts_file, "hosts.yaml")
                parse_hosts_yaml(hosts_content)
                params_content = self._read_required_file(params_file, "sap-parameters.yaml")
                extra_vars = parse_sap_parameters(params_content)
            except WorkspaceConfigError:
                logger.warning("Skipping workspace %s: invalid configuration", entry.name)
                continue

            sap_sid = str(extra_vars.get("sap_sid", "") or "")

            workspaces.append(
                WorkspaceSummary(
                    workspace_id=entry.name,
                    name=sap_sid or entry.name,
                    environment=extract_environment(entry.name),
                    path=str(resolved_entry),
                )
            )

        return workspaces

    def get_workspace_config(self, workspace_id: str) -> WorkspaceConfig:
        """Read workspace configuration from the filesystem."""
        validate_workspace_id(workspace_id)
        workspace_dir = self._get_workspace_dir(workspace_id)
        hosts_file = self._resolve_workspace_file(workspace_dir / "hosts.yaml")
        if not hosts_file.exists():
            raise WorkspaceConfigError(f"hosts.yaml missing for workspace {workspace_id}")

        parse_hosts_yaml(self._read_required_file(hosts_file, "hosts.yaml"))

        params_file = self._resolve_workspace_file(workspace_dir / "sap-parameters.yaml")
        if not params_file.exists():
            raise WorkspaceConfigError(f"sap-parameters.yaml missing for workspace {workspace_id}")
        extra_vars: dict[str, Any] = self._read_params_file(params_file)
        sap_sid = str(extra_vars.get("sap_sid", "") or "")
        db_sid = str(extra_vars.get("db_sid", "") or "")
        database_ha = bool(extra_vars.get("database_high_availability", False))
        scs_ha = bool(extra_vars.get("scs_high_availability", False))

        return WorkspaceConfig(
            workspace_id=workspace_id,
            inventory_path=str(hosts_file),
            sap_sid=sap_sid,
            db_sid=db_sid,
            database_high_availability=database_ha,
            scs_high_availability=scs_ha,
            extra_vars=extra_vars,
            path=str(workspace_dir),
        )

    def materialize(self, workspace_id: str, job_id: str) -> MaterializedWorkspace:
        """Return existing workspace path for job execution."""
        try:
            UUID(job_id)
        except ValueError as exc:
            raise WorkspaceValidationError(f"Job ID must be a UUID: {job_id}") from exc

        config = self.get_workspace_config(workspace_id)
        params_file = self._resolve_workspace_file(Path(config.path) / "sap-parameters.yaml")
        if not params_file.exists():
            raise WorkspaceConfigError(f"sap-parameters.yaml missing for workspace {workspace_id}")

        extra_vars = self._read_params_file(params_file)
        return MaterializedWorkspace(
            workspace_id=workspace_id,
            job_id=job_id,
            local_path=Path(config.path),
            inventory_path=config.inventory_path,
            extra_vars=extra_vars,
            owned=False,
        )

    def cleanup(self, materialized: MaterializedWorkspace) -> None:
        """Remove owned directories only."""
        if materialized.owned and materialized.local_path.exists():
            shutil.rmtree(materialized.local_path)

    def close(self) -> None:
        """No resources to release for filesystem backend."""

    def _get_workspace_dir(self, workspace_id: str) -> Path:
        workspace_dir = self._resolve_workspace_file(self._base / workspace_id)
        if not workspace_dir.exists() or not workspace_dir.is_dir():
            raise WorkspaceNotFoundError(f"Workspace {workspace_id} not found")
        return workspace_dir

    def _resolve_workspace_file(self, path: Path) -> Path:
        try:
            return self._resolve_within_base(path, self._base.resolve(strict=True))
        except FileNotFoundError:
            return path

    @staticmethod
    def _resolve_within_base(path: Path, base_resolved: Path) -> Path:
        resolved = path.resolve(strict=True)
        try:
            resolved.relative_to(base_resolved)
        except ValueError as exc:
            raise WorkspaceValidationError(f"Workspace path escapes base: {path.name}") from exc
        return resolved

    def _read_required_file(self, path: Path, display_name: str) -> bytes:
        if not path.exists():
            raise WorkspaceConfigError(f"{display_name} missing for workspace {path.parent.name}")
        size = path.stat().st_size
        if size > MAX_CONFIG_FILE_SIZE:
            raise WorkspaceConfigError(f"{display_name} exceeds {MAX_CONFIG_FILE_SIZE} byte limit")
        return path.read_bytes()

    def _read_params_file(self, path: Path) -> dict[str, Any]:
        return parse_sap_parameters(self._read_required_file(path, "sap-parameters.yaml"))
