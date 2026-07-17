# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Azure Blob Storage-based workspace backend implementation."""

from __future__ import annotations
import json
import os
import shutil
import stat
from pathlib import Path
from uuid import UUID, uuid4
from azure.core import MatchConditions
from azure.core.exceptions import ResourceModifiedError, ResourceNotFoundError
from src.core.contracts.storage import ContainerClientProtocol
from src.core.exceptions import (
    ETagMismatchError,
    WorkspaceBackendError,
    WorkspaceConfigError,
    WorkspaceNotFoundError,
    WorkspaceValidationError,
)
from src.core.models.workspace import (
    MaterializedWorkspace,
    WorkspaceConfig,
    WorkspaceManifest,
    WorkspaceSummary,
)
from src.core.observability import get_logger
from src.core.storage.workspace.validation import (
    MAX_CONFIG_FILE_SIZE,
    WORKSPACE_MANIFEST_FILE,
    extract_environment,
    parse_hosts_yaml,
    parse_sap_parameters,
    validate_workspace_id,
)

logger = get_logger(__name__)


class BlobWorkspaceBackend:
    """Azure Blob Storage-based workspace backend."""

    def __init__(
        self,
        *,
        container_client: ContainerClientProtocol,
        data_dir: Path | None = None,
    ) -> None:
        """Initialize blob workspace backend with a non-owning container client."""
        self._container_client = container_client
        self._data_dir = data_dir or Path("data")

        try:
            next(iter(self._container_client.list_blobs(results_per_page=1)), None)
        except Exception as exc:
            raise WorkspaceBackendError(f"Failed to connect to blob storage: {exc}") from exc

    @property
    def backend_name(self) -> str:
        """Return ``"blob"``."""
        return "blob"

    def list_workspaces(self) -> list[WorkspaceSummary]:
        """List workspaces by discovering committed workspace manifests.

        :returns: Valid committed workspaces.
        """
        workspaces: list[WorkspaceSummary] = []
        seen_lower: dict[str, str] = {}

        for prefix in self._container_client.walk_blobs(delimiter="/"):
            workspace_id = prefix.name.rstrip("/")
            try:
                validate_workspace_id(workspace_id)
            except WorkspaceValidationError:
                continue

            lower_id = workspace_id.lower()
            if lower_id in seen_lower:
                logger.warning(
                    "Case collision in blob: %s vs %s — skipping both",
                    workspace_id,
                    seen_lower[lower_id],
                )
                workspaces = [w for w in workspaces if w.workspace_id != seen_lower[lower_id]]
                continue
            seen_lower[lower_id] = workspace_id

            if not self._blob_exists(self._manifest_blob_name(workspace_id)):
                continue

            try:
                config = self.get_workspace_config(workspace_id)
            except (WorkspaceBackendError, WorkspaceConfigError, ETagMismatchError):
                logger.warning("Skipping invalid blob workspace %s", workspace_id, exc_info=True)
                continue

            workspaces.append(
                WorkspaceSummary(
                    workspace_id=workspace_id,
                    name=config.sap_sid or workspace_id,
                    environment=extract_environment(workspace_id),
                )
            )

        return workspaces

    def get_workspace_config(self, workspace_id: str) -> WorkspaceConfig:
        """Read workspace configuration from blob storage.

        :param workspace_id: Workspace identifier.
        :returns: Parsed workspace configuration.
        """
        validate_workspace_id(workspace_id)
        manifest, hosts_content, params_content = self._load_consistent_workspace_pair(workspace_id)
        del manifest

        parse_hosts_yaml(hosts_content)
        extra_vars = parse_sap_parameters(params_content)
        return WorkspaceConfig(
            workspace_id=workspace_id,
            inventory_path=f"{workspace_id}/hosts.yaml",
            sap_sid=str(extra_vars.get("sap_sid", "") or ""),
            db_sid=str(extra_vars.get("db_sid", "") or ""),
            database_high_availability=bool(extra_vars.get("database_high_availability", False)),
            scs_high_availability=bool(extra_vars.get("scs_high_availability", False)),
            extra_vars=extra_vars,
        )

    def materialize(self, workspace_id: str, job_id: str) -> MaterializedWorkspace:
        """Materialize a workspace revision into an isolated local directory.

        :param workspace_id: Workspace identifier.
        :param job_id: Job UUID that owns the materialized directory.
        :returns: Materialized workspace paths and execution variables.
        """
        validate_workspace_id(workspace_id)
        try:
            parsed_job_id = UUID(job_id)
        except ValueError as exc:
            raise WorkspaceValidationError(f"Job ID must be a UUID: {job_id}") from exc

        manifest, hosts_content, params_content = self._load_consistent_workspace_pair(workspace_id)
        del manifest
        parse_hosts_yaml(hosts_content)
        extra_vars = parse_sap_parameters(params_content)

        workspaces_root = self._data_dir / "workspaces"
        workspaces_root.mkdir(parents=True, exist_ok=True)
        target_dir = workspaces_root / str(parsed_job_id)
        temp_dir = workspaces_root / f".{parsed_job_id}.tmp-{uuid4()}"

        if target_dir.exists() or target_dir.is_symlink():
            raise WorkspaceValidationError(
                f"Materialization target already exists for job {parsed_job_id}"
            )

        try:
            temp_dir.mkdir(parents=False, exist_ok=False)
            self._set_directory_permissions(temp_dir)

            hosts_path = temp_dir / "hosts.yaml"
            hosts_path.write_bytes(hosts_content)
            self._set_file_permissions(hosts_path)

            params_path = temp_dir / "sap-parameters.yaml"
            params_path.write_bytes(params_content)
            self._set_file_permissions(params_path)

            parse_hosts_yaml(hosts_path.read_bytes())
            parse_sap_parameters(params_path.read_bytes())

            temp_dir.replace(target_dir)
        except Exception:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            raise

        return MaterializedWorkspace(
            workspace_id=workspace_id,
            job_id=str(parsed_job_id),
            local_path=target_dir,
            inventory_path=str(target_dir / "hosts.yaml"),
            extra_vars=extra_vars,
            owned=True,
        )

    def cleanup(self, materialized: MaterializedWorkspace) -> None:
        """Remove the materialized directory if owned."""
        if materialized.owned and materialized.local_path.exists():
            shutil.rmtree(materialized.local_path)

    def close(self) -> None:
        """Blob backends use a non-owning container client and do not close it."""

    def _manifest_blob_name(self, workspace_id: str) -> str:
        return f"{workspace_id}/{WORKSPACE_MANIFEST_FILE}"

    def _workspace_exists(self, workspace_id: str) -> bool:
        return self._blob_exists(f"{workspace_id}/")

    def _blob_exists(self, name_prefix: str) -> bool:
        return any(self._container_client.list_blobs(name_starts_with=name_prefix))

    def _load_consistent_workspace_pair(
        self, workspace_id: str
    ) -> tuple[WorkspaceManifest, bytes, bytes]:
        """Load manifest, hosts.yaml, and sap-parameters.yaml from one revision."""
        manifest_blob = self._manifest_blob_name(workspace_id)
        try:
            manifest_bytes, manifest_etag = self._read_blob_bounded(manifest_blob)
        except WorkspaceNotFoundError as exc:
            if self._workspace_exists(workspace_id):
                raise WorkspaceConfigError(
                    f"Workspace {workspace_id} is missing {WORKSPACE_MANIFEST_FILE}"
                ) from exc
            raise WorkspaceNotFoundError(f"Workspace {workspace_id} not found") from exc

        manifest = self._parse_manifest(manifest_bytes, workspace_id)
        try:
            hosts_content, hosts_etag = self._read_blob_bounded(
                f"{workspace_id}/hosts.yaml",
                expected_etag=manifest.hosts_yaml_etag,
            )
            params_content, params_etag = self._read_blob_bounded(
                f"{workspace_id}/sap-parameters.yaml",
                expected_etag=manifest.sap_parameters_yaml_etag,
            )
        except WorkspaceNotFoundError as exc:
            raise WorkspaceConfigError(
                f"Workspace {workspace_id} is missing required configuration blobs"
            ) from exc

        if (
            hosts_etag != manifest.hosts_yaml_etag
            or params_etag != manifest.sap_parameters_yaml_etag
        ):
            raise ETagMismatchError(f"Workspace {workspace_id} revision changed during read")

        _, verified_manifest_etag = self._read_blob_bounded(manifest_blob)
        if verified_manifest_etag != manifest_etag:
            raise ETagMismatchError(
                f"Workspace {workspace_id} manifest changed during read: "
                f"{manifest_etag} -> {verified_manifest_etag}"
            )

        return manifest, hosts_content, params_content

    def _parse_manifest(self, content: bytes, workspace_id: str) -> WorkspaceManifest:
        """Parse a workspace manifest."""
        try:
            raw = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkspaceConfigError(
                f"Workspace {workspace_id} has malformed {WORKSPACE_MANIFEST_FILE}: {exc}"
            ) from exc

        if not isinstance(raw, dict):
            raise WorkspaceConfigError(
                f"Workspace {workspace_id} has malformed {WORKSPACE_MANIFEST_FILE}: expected object"
            )

        try:
            manifest = WorkspaceManifest(
                schema_version=int(raw["schema_version"]),
                revision=str(raw["revision"]),
                hosts_yaml_etag=str(raw["hosts_yaml_etag"]),
                sap_parameters_yaml_etag=str(raw["sap_parameters_yaml_etag"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkspaceConfigError(
                f"Workspace {workspace_id} has malformed {WORKSPACE_MANIFEST_FILE}: {exc}"
            ) from exc

        if manifest.schema_version != 1:
            raise WorkspaceConfigError(
                "Workspace "
                f"{workspace_id} has unsupported manifest schema {manifest.schema_version}"
            )
        if (
            not manifest.revision
            or not manifest.hosts_yaml_etag
            or not manifest.sap_parameters_yaml_etag
        ):
            raise WorkspaceConfigError(
                f"Workspace {workspace_id} has incomplete {WORKSPACE_MANIFEST_FILE}"
            )
        return manifest

    def _read_blob_bounded(
        self,
        blob_name: str,
        *,
        expected_etag: str | None = None,
    ) -> tuple[bytes, str]:
        """Read a blob with size bounds and optional optimistic concurrency."""
        blob_client = self._container_client.get_blob_client(blob_name)
        try:
            props = blob_client.get_blob_properties()
        except ResourceNotFoundError as exc:
            raise WorkspaceNotFoundError(f"Blob not found: {blob_name}") from exc

        if props.size > MAX_CONFIG_FILE_SIZE:
            raise WorkspaceConfigError(f"{blob_name} exceeds {MAX_CONFIG_FILE_SIZE} byte limit")

        if expected_etag is not None and props.etag != expected_etag:
            raise ETagMismatchError(
                f"Blob {blob_name} ETag mismatch: expected {expected_etag}, got {props.etag}"
            )

        try:
            stream = blob_client.download_blob(
                etag=expected_etag,
                match_condition=(
                    MatchConditions.IfNotModified if expected_etag is not None else None
                ),
                max_concurrency=1,
            )
            content = stream.readall()
        except ResourceNotFoundError as exc:
            raise WorkspaceNotFoundError(f"Blob not found: {blob_name}") from exc
        except ResourceModifiedError as exc:
            raise ETagMismatchError(f"Blob {blob_name} changed during read") from exc
        except TypeError as exc:
            raise WorkspaceBackendError(f"Failed to read blob {blob_name}: {exc}") from exc

        if len(content) > MAX_CONFIG_FILE_SIZE:
            raise WorkspaceConfigError(f"{blob_name} exceeds {MAX_CONFIG_FILE_SIZE} byte limit")

        return content, props.etag

    @staticmethod
    def _set_directory_permissions(path: Path) -> None:
        if os.name != "nt":
            os.chmod(path, stat.S_IRWXU)

    @staticmethod
    def _set_file_permissions(path: Path) -> None:
        if os.name != "nt":
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
