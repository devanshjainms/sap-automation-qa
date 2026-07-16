# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for workspace backends and factory selection."""

import json
import tempfile
from collections.abc import Generator, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from pytest_mock import MockerFixture
import pytest
from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import ContainerClient
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
    mutable_workspace_vars,
)
from src.core.storage.workspace import (
    BlobWorkspaceBackend,
    FilesystemWorkspaceBackend,
    create_workspace_backend,
)
from src.core.storage.workspace.validation import (
    MAX_CONFIG_FILE_SIZE,
    WORKSPACE_MANIFEST_FILE,
    parse_hosts_yaml,
    parse_sap_parameters,
    validate_workspace_id,
)


@pytest.fixture
def ws_base() -> Generator[Path, None, None]:
    """Provide a temporary WORKSPACES/SYSTEM directory tree for filesystem backend tests."""
    with tempfile.TemporaryDirectory() as td:
        base = Path(td) / "WORKSPACES" / "SYSTEM"
        base.mkdir(parents=True)
        yield base


@pytest.fixture
def data_dir() -> Generator[Path, None, None]:
    """Provide a temporary data directory for materialized workspace storage."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def fs_backend(ws_base: Path, data_dir: Path) -> FilesystemWorkspaceBackend:
    """Create a FilesystemWorkspaceBackend rooted at the temporary ws_base."""
    return FilesystemWorkspaceBackend(workspaces_base=ws_base, data_dir=data_dir)


def _create_ws(
    base: Path, name: str, *, hosts: str = "all:\n  hosts:\n", params: str | None = None
) -> Path:
    """Create a minimal workspace directory with hosts.yaml and optional sap-parameters.yaml."""
    workspace = base / name
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "hosts.yaml").write_text(hosts, encoding="utf-8")
    if params is not None:
        (workspace / "sap-parameters.yaml").write_text(params, encoding="utf-8")
    return workspace


class FakeBlobClient:
    """In-memory blob client that simulates etag-based conditional downloads."""

    def __init__(self, name: str, data: bytes, etag_source) -> None:
        """Initialize with blob name, content bytes, and a callable returning the current etag."""
        self.name = name
        self._data = data
        self._etag_source = etag_source

    def get_blob_properties(self):
        """Return a namespace with size and current etag for the blob."""
        etag = self._etag_source()
        return SimpleNamespace(size=len(self._data), etag=etag)

    def download_blob(self, **kwargs):
        """Download blob content, raising ResourceModifiedError on etag mismatch."""
        expected_etag = kwargs.get("etag")
        current_etag = self._etag_source()
        if expected_etag is not None and expected_etag != current_etag:
            from azure.core.exceptions import ResourceModifiedError

            raise ResourceModifiedError("etag changed")
        return SimpleNamespace(readall=lambda: self._data)


class _FakeMock:
    """Minimal callable mock supporting side_effect and child attribute access."""

    def __init__(self):
        """Initialize call tracking and child attribute storage."""
        self._children = {}
        self.side_effect = None
        self.call_count = 0
        self.called = False

    def __getattr__(self, name):
        """Lazily create child _FakeMock instances for attribute access."""
        if name.startswith("_") or name in ("side_effect", "call_count", "called"):
            raise AttributeError(name)
        if name not in self._children:
            self._children[name] = _FakeMock()
        return self._children[name]

    def __call__(self, *args, **kwargs):
        """Invoke the mock, incrementing counters and optionally triggering side_effect."""
        self.called = True
        self.call_count += 1
        if self.side_effect is not None:
            if isinstance(self.side_effect, BaseException):
                raise self.side_effect
            if isinstance(self.side_effect, type) and issubclass(self.side_effect, BaseException):
                raise self.side_effect()
            if callable(self.side_effect):
                return self.side_effect(*args, **kwargs)
        return _FakeMock()

    def assert_not_called(self):
        """Assert that this mock was never invoked."""
        assert not self.called


class FakeContainerClient:
    """In-memory container client simulating blob listing and client retrieval."""

    def __init__(
        self,
        blobs: dict[str, bytes],
        etags: Mapping[str, list[str] | str],
        mock_factory=None,
    ) -> None:
        """Initialize with a dict of blob name to content, etag sequences, and mock factory."""
        self._blobs = blobs
        self._etags = dict(etags)
        self._counters = {name: 0 for name in etags}
        self._mock_factory = mock_factory or _FakeMock
        self.close = self._mock_factory()

    def list_blobs(self, name_starts_with: str = "", **kwargs):
        """List blobs whose names start with the given prefix."""
        return [
            SimpleNamespace(name=name) for name in self._blobs if name.startswith(name_starts_with)
        ]

    def walk_blobs(self, delimiter: str = "/", **kwargs):
        """Return top-level blob prefixes using the specified delimiter."""
        prefixes = sorted({name.split("/")[0] + "/" for name in self._blobs if "/" in name})
        return [SimpleNamespace(name=prefix) for prefix in prefixes]

    def get_blob_client(self, blob_name: str):
        """Return a FakeBlobClient for existing blobs or a mock raising ResourceNotFoundError."""
        if blob_name not in self._blobs:
            client = self._mock_factory()
            client.get_blob_properties.side_effect = ResourceNotFoundError("missing")
            client.download_blob.side_effect = ResourceNotFoundError("missing")
            return client

        def current_etag() -> str:
            """Return the current etag for the blob, advancing through a list if configured."""
            values = self._etags.get(blob_name, "etag-default")
            if isinstance(values, list):
                index = self._counters[blob_name]
                self._counters[blob_name] = min(index + 1, len(values) - 1)
                return values[index]
            return values

        return FakeBlobClient(blob_name, self._blobs[blob_name], current_etag)


class TestWorkspaceBackend:
    """Verify workspace validation, filesystem backend, blob backend, and factory selection."""

    def test_validate_workspace_id_accepts_valid_values(self) -> None:
        """Accept and return a valid workspace ID string unchanged."""
        assert validate_workspace_id("DEV-EUS2-SAP01") == "DEV-EUS2-SAP01"

    def test_validate_workspace_id_rejects_empty(self) -> None:
        """Raise WorkspaceValidationError for an empty workspace ID string."""
        with pytest.raises(WorkspaceValidationError, match="must not be empty"):
            validate_workspace_id("")

    def test_validate_workspace_id_rejects_null_byte(self) -> None:
        """Raise WorkspaceValidationError when workspace ID contains a null byte."""
        with pytest.raises(WorkspaceValidationError, match="null byte"):
            validate_workspace_id("abc\x00def")

    def test_validate_workspace_id_rejects_too_long(self) -> None:
        """Raise WorkspaceValidationError when workspace ID exceeds 128 characters."""
        with pytest.raises(WorkspaceValidationError, match="128"):
            validate_workspace_id("a" * 129)

    def test_validate_workspace_id_rejects_invalid_characters(self) -> None:
        """Raise WorkspaceValidationError for IDs containing slashes or leading dots."""
        for workspace_id in ("../etc", "foo/bar", ".hidden"):
            with pytest.raises(WorkspaceValidationError):
                validate_workspace_id(workspace_id)

    def test_validate_workspace_id_rejects_path_traversal(self) -> None:
        """Raise WorkspaceValidationError for IDs containing path traversal components."""
        import os

        traversal_id = f"a{os.sep}..{os.sep}b" if os.sep != "/" else "a/../b"
        with pytest.raises(WorkspaceValidationError):
            validate_workspace_id(traversal_id)

    def test_parse_hosts_yaml_requires_non_empty_mapping(self) -> None:
        """Raise WorkspaceConfigError when hosts.yaml is not a non-empty YAML mapping."""
        with pytest.raises(WorkspaceConfigError, match="mapping"):
            parse_hosts_yaml(b"- item")
        with pytest.raises(WorkspaceConfigError, match="must not be empty"):
            parse_hosts_yaml(b"{}")

    def test_parse_sap_parameters_requires_mapping(self) -> None:
        """Raise WorkspaceConfigError when sap-parameters.yaml is not a YAML mapping."""
        with pytest.raises(WorkspaceConfigError, match="mapping"):
            parse_sap_parameters(b"- item")

    def test_parse_sap_parameters_allows_empty_mapping(self) -> None:
        """Accept an empty YAML mapping as valid sap-parameters content."""
        result = parse_sap_parameters(b"{}")
        assert result == {}

    def test_parse_hosts_yaml_rejects_malformed_yaml(self) -> None:
        """Raise WorkspaceConfigError for syntactically invalid YAML in hosts content."""
        with pytest.raises(WorkspaceConfigError, match="Malformed"):
            parse_hosts_yaml(b":\n  :\n    - [invalid")

    def test_parse_rejects_oversized_content(self) -> None:
        """Raise WorkspaceConfigError when content exceeds MAX_CONFIG_FILE_SIZE bytes."""
        with pytest.raises(WorkspaceConfigError, match="byte limit"):
            parse_hosts_yaml(b"x" * (MAX_CONFIG_FILE_SIZE + 1))

    def test_extract_environment_from_workspace_id(self) -> None:
        """Extract the environment prefix from workspace IDs using hyphen as delimiter."""
        from src.core.storage.workspace.validation import extract_environment

        assert extract_environment("DEV-EUS2-SAP01") == "DEV"
        assert extract_environment("PROD") == ""

    def test_backend_name(self, fs_backend: FilesystemWorkspaceBackend) -> None:
        """Verify the filesystem backend reports its name as 'filesystem'."""
        assert fs_backend.backend_name == "filesystem"

    def test_get_workspace_config(
        self, ws_base: Path, fs_backend: FilesystemWorkspaceBackend
    ) -> None:
        """Load workspace config from filesystem and verify sap_sid and HA flag are parsed."""
        _create_ws(ws_base, "DEV-WS-01", params="sap_sid: HDB\ndatabase_high_availability: true\n")
        config = fs_backend.get_workspace_config("DEV-WS-01")
        assert config.sap_sid == "HDB"
        assert config.database_high_availability is True

    def test_materialize_requires_sap_parameters(
        self, ws_base: Path, fs_backend: FilesystemWorkspaceBackend
    ) -> None:
        """Raise WorkspaceConfigError when sap-parameters.yaml is missing during materialization."""
        _create_ws(ws_base, "DEV-WS-01")
        with pytest.raises(WorkspaceConfigError, match="sap-parameters.yaml missing"):
            fs_backend.materialize("DEV-WS-01", "d1c73be2-7d55-479d-8b97-2d63d5d032d8")

    def test_materialize_rejects_non_uuid_job_id(
        self, ws_base: Path, fs_backend: FilesystemWorkspaceBackend
    ) -> None:
        """Raise WorkspaceValidationError when job_id is not a valid UUID string."""
        _create_ws(ws_base, "DEV-WS-01", params="sap_sid: HDB\n")
        with pytest.raises(WorkspaceValidationError, match="UUID"):
            fs_backend.materialize("DEV-WS-01", "job-123")

    def test_symlink_escape_is_rejected(
        self, ws_base: Path, fs_backend: FilesystemWorkspaceBackend
    ) -> None:
        """Raise WorkspaceValidationError when workspace path is a symlink escaping the base."""
        external = Path(tempfile.mkdtemp())
        try:
            (external / "hosts.yaml").write_text("all:\n", encoding="utf-8")
            (external / "sap-parameters.yaml").write_text("sap_sid: HDB\n", encoding="utf-8")
            link_path = ws_base / "ESCAPE-WS"
            try:
                link_path.symlink_to(external)
            except OSError:
                pytest.skip("Symlinks not supported on this platform")
            with pytest.raises(WorkspaceValidationError):
                fs_backend.get_workspace_config("ESCAPE-WS")
        finally:
            if external.exists():
                for child in external.iterdir():
                    child.unlink()
                external.rmdir()

    def test_oversized_file_rejected_before_read(
        self, ws_base: Path, fs_backend: FilesystemWorkspaceBackend
    ) -> None:
        """Raise WorkspaceConfigError when hosts.yaml on disk exceeds MAX_CONFIG_FILE_SIZE."""
        workspace = _create_ws(ws_base, "BIG-WS", params="sap_sid: HDB\n")
        hosts_file = workspace / "hosts.yaml"
        hosts_file.write_bytes(b"x" * (MAX_CONFIG_FILE_SIZE + 1))
        with pytest.raises(WorkspaceConfigError, match="byte limit"):
            fs_backend.get_workspace_config("BIG-WS")

    def test_cleanup_not_owned_is_noop(
        self, ws_base: Path, fs_backend: FilesystemWorkspaceBackend
    ) -> None:
        """Leave the materialized directory intact when cleanup is called on a non-owned workspace."""
        _create_ws(ws_base, "DEV-WS-01", params="sap_sid: HDB\n")
        materialized = fs_backend.materialize("DEV-WS-01", "d1c73be2-7d55-479d-8b97-2d63d5d032d8")
        fs_backend.cleanup(materialized)
        assert materialized.local_path.exists()

    def test_list_workspaces_skips_missing_params(
        self, ws_base: Path, fs_backend: FilesystemWorkspaceBackend
    ) -> None:
        """Exclude workspaces missing sap-parameters.yaml from the listing."""
        _create_ws(ws_base, "HOSTS-ONLY")
        assert fs_backend.list_workspaces() == []

    def test_list_workspaces_skips_malformed_hosts(
        self, ws_base: Path, fs_backend: FilesystemWorkspaceBackend
    ) -> None:
        """Exclude workspaces with malformed hosts.yaml from the listing."""
        _create_ws(ws_base, "BAD-HOSTS", hosts="- bad", params="sap_sid: HDB\n")
        assert fs_backend.list_workspaces() == []

    def test_list_workspaces_returns_valid_entries(
        self, ws_base: Path, fs_backend: FilesystemWorkspaceBackend
    ) -> None:
        """Return workspace entries for directories with valid hosts and parameters files."""
        _create_ws(ws_base, "PROD-WS-01", params="sap_sid: X01\n")
        workspaces = fs_backend.list_workspaces()
        assert len(workspaces) == 1
        assert workspaces[0].workspace_id == "PROD-WS-01"

    def test_list_workspaces_skips_hidden_directories(
        self, ws_base: Path, fs_backend: FilesystemWorkspaceBackend
    ) -> None:
        """Exclude directories whose names start with a dot from workspace listing."""
        hidden = ws_base / ".hidden"
        hidden.mkdir()
        (hidden / "hosts.yaml").write_text("all:\n  hosts:\n    n1:\n", encoding="utf-8")
        (hidden / "sap-parameters.yaml").write_text("sap_sid: HDB\n", encoding="utf-8")
        assert fs_backend.list_workspaces() == []

    def test_get_workspace_config_missing_workspace_raises(
        self, fs_backend: FilesystemWorkspaceBackend
    ) -> None:
        """Raise WorkspaceNotFoundError when the workspace directory does not exist."""
        with pytest.raises(WorkspaceNotFoundError, match="not found"):
            fs_backend.get_workspace_config("MISSING-WS")

    def test_get_workspace_config_missing_hosts_raises(
        self, ws_base: Path, fs_backend: FilesystemWorkspaceBackend
    ) -> None:
        """Raise WorkspaceConfigError when hosts.yaml is missing from the workspace directory."""
        workspace = ws_base / "NO-HOSTS"
        workspace.mkdir()
        (workspace / "sap-parameters.yaml").write_text("sap_sid: HDB\n", encoding="utf-8")
        with pytest.raises(WorkspaceConfigError, match="hosts.yaml missing"):
            fs_backend.get_workspace_config("NO-HOSTS")

    def test_close_is_noop(self, fs_backend: FilesystemWorkspaceBackend) -> None:
        """Verify the filesystem backend close method does not raise."""
        fs_backend.close()

    def test_list_workspaces_handles_case_collision(
        self, ws_base: Path, fs_backend: FilesystemWorkspaceBackend
    ) -> None:
        """Exclude both workspaces when a case-insensitive collision is detected."""
        import os

        if os.name == "nt":
            pytest.skip("Case-insensitive filesystem merges these directories")
        _create_ws(ws_base, "DevWS", params="sap_sid: A\n")
        _create_ws(ws_base, "devws", params="sap_sid: B\n")
        workspaces = fs_backend.list_workspaces()
        assert len(workspaces) == 0

    def test_materialize_returns_materialized_workspace(
        self, ws_base: Path, fs_backend: FilesystemWorkspaceBackend
    ) -> None:
        """Return a MaterializedWorkspace with correct metadata and non-owned flag."""
        _create_ws(ws_base, "DEV-WS-01", params="sap_sid: HDB\n")
        job_id = "d1c73be2-7d55-479d-8b97-2d63d5d032d8"
        materialized = fs_backend.materialize("DEV-WS-01", job_id)
        assert materialized.workspace_id == "DEV-WS-01"
        assert materialized.job_id == job_id
        assert materialized.owned is False
        assert materialized.extra_vars["sap_sid"] == "HDB"

    def test_list_workspaces_empty_base_returns_empty(self, data_dir: Path) -> None:
        """Return an empty list when the workspaces base directory does not exist."""
        non_existent = data_dir / "no-such-dir"
        backend = FilesystemWorkspaceBackend(workspaces_base=non_existent)
        assert backend.list_workspaces() == []

    def _make_backend(
        self,
        data_dir: Path,
        blobs: dict[str, bytes],
        etags: Mapping[str, list[str] | str],
        mock_factory=None,
    ) -> tuple[BlobWorkspaceBackend, FakeContainerClient]:
        """Create a BlobWorkspaceBackend backed by a FakeContainerClient for testing."""
        container = FakeContainerClient(blobs, etags, mock_factory=mock_factory)
        return (
            BlobWorkspaceBackend(
                container_client=cast(ContainerClient, container),
                data_dir=data_dir,
            ),
            container,
        )

    def test_blob_backend_name(self, data_dir: Path) -> None:
        """Verify the blob backend reports its name as 'blob'."""
        backend, _ = self._make_backend(data_dir, {}, {})
        assert backend.backend_name == "blob"

    def test_get_workspace_config_uses_manifest_revision(self, data_dir: Path) -> None:
        """Load workspace config from blob using manifest etags for consistent reads."""
        manifest = json.dumps(
            {
                "schema_version": 1,
                "revision": "r1",
                "hosts_yaml_etag": "hosts-v1",
                "sap_parameters_yaml_etag": "params-v1",
            }
        ).encode("utf-8")
        blobs = {
            f"WS-01/{WORKSPACE_MANIFEST_FILE}": manifest,
            "WS-01/hosts.yaml": b"all:\n  hosts:\n    node1:\n",
            "WS-01/sap-parameters.yaml": b"sap_sid: HDB\n",
        }
        etags = {
            f"WS-01/{WORKSPACE_MANIFEST_FILE}": ["manifest-v1", "manifest-v1"],
            "WS-01/hosts.yaml": "hosts-v1",
            "WS-01/sap-parameters.yaml": "params-v1",
        }
        backend, _ = self._make_backend(data_dir, blobs, etags)
        config = backend.get_workspace_config("WS-01")
        assert config.sap_sid == "HDB"

    def test_manifest_change_raises_etag_mismatch(self, data_dir: Path) -> None:
        """Raise ETagMismatchError when the manifest etag changes between reads."""
        manifest = json.dumps(
            {
                "schema_version": 1,
                "revision": "r1",
                "hosts_yaml_etag": "hosts-v1",
                "sap_parameters_yaml_etag": "params-v1",
            }
        ).encode("utf-8")
        blobs = {
            f"WS-01/{WORKSPACE_MANIFEST_FILE}": manifest,
            "WS-01/hosts.yaml": b"all:\n  hosts:\n",
            "WS-01/sap-parameters.yaml": b"sap_sid: HDB\n",
        }
        etags = {
            f"WS-01/{WORKSPACE_MANIFEST_FILE}": ["manifest-v1", "manifest-v2"],
            "WS-01/hosts.yaml": "hosts-v1",
            "WS-01/sap-parameters.yaml": "params-v1",
        }
        backend, _ = self._make_backend(data_dir, blobs, etags)
        with pytest.raises(ETagMismatchError):
            backend.get_workspace_config("WS-01")

    def test_missing_manifest_for_existing_workspace_is_config_error(
        self, data_dir: Path, mocker: MockerFixture
    ) -> None:
        """Raise WorkspaceConfigError when blobs exist but the manifest file is missing."""
        blobs = {
            "WS-01/hosts.yaml": b"all:\n  hosts:\n",
            "WS-01/sap-parameters.yaml": b"sap_sid: HDB\n",
        }
        etags = {"WS-01/hosts.yaml": "hosts-v1", "WS-01/sap-parameters.yaml": "params-v1"}
        backend, _ = self._make_backend(data_dir, blobs, etags)
        with pytest.raises(WorkspaceConfigError, match=WORKSPACE_MANIFEST_FILE):
            backend.get_workspace_config("WS-01")

    def test_materialize_builds_atomic_directory(self, data_dir: Path) -> None:
        """Create the materialized workspace directory atomically without leftover temp dirs."""
        manifest = json.dumps(
            {
                "schema_version": 1,
                "revision": "r1",
                "hosts_yaml_etag": "hosts-v1",
                "sap_parameters_yaml_etag": "params-v1",
            }
        ).encode("utf-8")
        blobs = {
            f"WS-01/{WORKSPACE_MANIFEST_FILE}": manifest,
            "WS-01/hosts.yaml": b"all:\n  hosts:\n    node1:\n",
            "WS-01/sap-parameters.yaml": b"sap_sid: HDB\n",
        }
        etags = {
            f"WS-01/{WORKSPACE_MANIFEST_FILE}": ["manifest-v1", "manifest-v1"],
            "WS-01/hosts.yaml": "hosts-v1",
            "WS-01/sap-parameters.yaml": "params-v1",
        }
        backend, _ = self._make_backend(data_dir, blobs, etags)
        job_id = "d1c73be2-7d55-479d-8b97-2d63d5d032d8"
        materialized = backend.materialize("WS-01", job_id)
        assert materialized.local_path.name == job_id
        assert (materialized.local_path / "hosts.yaml").exists()
        assert not any(
            path.name.startswith(f".{job_id}.tmp")
            for path in materialized.local_path.parent.iterdir()
        )

    def test_materialize_rejects_invalid_job_id(self, data_dir: Path) -> None:
        """Raise WorkspaceValidationError for non-UUID job_id in blob backend materialize."""
        backend, _ = self._make_backend(data_dir, {}, {})
        with pytest.raises(WorkspaceValidationError, match="UUID"):
            backend.materialize("WS-01", "job-123")

    def test_materialize_rejects_preexisting_target(self, data_dir: Path) -> None:
        """Raise WorkspaceValidationError when the materialization target directory already exists."""
        manifest = json.dumps(
            {
                "schema_version": 1,
                "revision": "r1",
                "hosts_yaml_etag": "hosts-v1",
                "sap_parameters_yaml_etag": "params-v1",
            }
        ).encode("utf-8")
        blobs = {
            f"WS-01/{WORKSPACE_MANIFEST_FILE}": manifest,
            "WS-01/hosts.yaml": b"all:\n  hosts:\n    node1:\n",
            "WS-01/sap-parameters.yaml": b"sap_sid: HDB\n",
        }
        etags = {
            f"WS-01/{WORKSPACE_MANIFEST_FILE}": ["manifest-v1", "manifest-v1"],
            "WS-01/hosts.yaml": "hosts-v1",
            "WS-01/sap-parameters.yaml": "params-v1",
        }
        backend, _ = self._make_backend(data_dir, blobs, etags)
        job_id = "d1c73be2-7d55-479d-8b97-2d63d5d032d8"
        target_dir = data_dir / "workspaces" / job_id
        target_dir.mkdir(parents=True)
        with pytest.raises(WorkspaceValidationError, match="already exists"):
            backend.materialize("WS-01", job_id)

    def test_cleanup_removes_owned_directory(self, data_dir: Path, mocker: MockerFixture) -> None:
        """Remove the materialized directory when cleanup is called on an owned workspace."""
        materialized = MaterializedWorkspace(
            workspace_id="WS-01",
            job_id="d1c73be2-7d55-479d-8b97-2d63d5d032d8",
            local_path=data_dir / "workspaces" / "d1c73be2-7d55-479d-8b97-2d63d5d032d8",
            inventory_path="hosts.yaml",
            extra_vars={},
            owned=True,
        )
        materialized.local_path.mkdir(parents=True)
        BlobWorkspaceBackend(
            container_client=cast(
                ContainerClient,
                FakeContainerClient({}, {}, mock_factory=mocker.MagicMock),
            ),
            data_dir=data_dir,
        ).cleanup(materialized)
        assert not materialized.local_path.exists()

    def test_cleanup_skips_non_owned(self, data_dir: Path, mocker: MockerFixture) -> None:
        """Leave the materialized directory intact when cleanup is called on non-owned workspace."""
        materialized = MaterializedWorkspace(
            workspace_id="WS-01",
            job_id="d1c73be2-7d55-479d-8b97-2d63d5d032d8",
            local_path=data_dir / "workspaces" / "d1c73be2-7d55-479d-8b97-2d63d5d032d8",
            inventory_path="hosts.yaml",
            extra_vars={},
            owned=False,
        )
        materialized.local_path.mkdir(parents=True)
        BlobWorkspaceBackend(
            container_client=cast(
                ContainerClient,
                FakeContainerClient({}, {}, mock_factory=mocker.MagicMock),
            ),
            data_dir=data_dir,
        ).cleanup(materialized)
        assert materialized.local_path.exists()

    def test_close_is_noop_for_non_owning_container(
        self, data_dir: Path, mocker: MockerFixture
    ) -> None:
        """Do not close the container client when the blob backend does not own it."""
        backend, container = self._make_backend(data_dir, {}, {}, mock_factory=mocker.MagicMock)
        close_mock = container.close
        backend.close()
        close_mock.assert_not_called()

    def test_read_blob_bounded_wraps_type_error_as_backend_error(
        self, data_dir: Path, mocker: MockerFixture
    ) -> None:
        """Wrap unexpected TypeError from download_blob into WorkspaceBackendError."""
        container = FakeContainerClient({}, {}, mock_factory=mocker.MagicMock)
        blob_client = mocker.MagicMock()
        blob_client.get_blob_properties.return_value = SimpleNamespace(size=1, etag="etag-v1")
        blob_client.download_blob.side_effect = TypeError("unsupported etag kwargs")
        container.get_blob_client = mocker.MagicMock(return_value=blob_client)
        backend = BlobWorkspaceBackend(
            container_client=cast(ContainerClient, container),
            data_dir=data_dir,
        )

        with pytest.raises(WorkspaceBackendError, match="Failed to read blob"):
            backend._read_blob_bounded("WS-01/hosts.yaml", expected_etag="etag-v1")

    def test_read_blob_bounded_rejects_stale_oversized_download(
        self, data_dir: Path, mocker: MockerFixture
    ) -> None:
        """Raise WorkspaceConfigError when downloaded content exceeds MAX_CONFIG_FILE_SIZE."""
        container = FakeContainerClient({}, {}, mock_factory=mocker.MagicMock)
        blob_client = mocker.MagicMock()
        blob_client.get_blob_properties.return_value = SimpleNamespace(
            size=MAX_CONFIG_FILE_SIZE - 1,
            etag="etag-v1",
        )
        blob_client.download_blob.return_value = SimpleNamespace(
            readall=lambda: b"x" * (MAX_CONFIG_FILE_SIZE + 1)
        )
        container.get_blob_client = mocker.MagicMock(return_value=blob_client)
        backend = BlobWorkspaceBackend(
            container_client=cast(ContainerClient, container),
            data_dir=data_dir,
        )

        with pytest.raises(WorkspaceConfigError, match="byte limit"):
            backend._read_blob_bounded("WS-01/hosts.yaml", expected_etag="etag-v1")

    def test_missing_workspace_raises_not_found(
        self, data_dir: Path, mocker: MockerFixture
    ) -> None:
        """Raise WorkspaceNotFoundError when the workspace has no blobs in the container."""
        backend, _ = self._make_backend(data_dir, {}, {})
        with pytest.raises(WorkspaceNotFoundError, match="not found"):
            backend.get_workspace_config("MISSING-WS")

    def test_parse_manifest_rejects_non_dict(self, data_dir: Path) -> None:
        """Raise WorkspaceConfigError when the manifest JSON is not an object."""
        backend, _ = self._make_backend(data_dir, {}, {})
        with pytest.raises(WorkspaceConfigError, match="expected object"):
            backend._parse_manifest(b"[]", "WS-01")

    def test_parse_manifest_rejects_bad_json(self, data_dir: Path) -> None:
        """Raise WorkspaceConfigError when manifest content is malformed JSON."""
        backend, _ = self._make_backend(data_dir, {}, {})
        with pytest.raises(WorkspaceConfigError, match="malformed"):
            backend._parse_manifest(b"{not-json", "WS-01")

    def test_parse_manifest_rejects_unsupported_schema(self, data_dir: Path) -> None:
        """Raise WorkspaceConfigError when manifest schema_version is not supported."""
        manifest = json.dumps(
            {
                "schema_version": 99,
                "revision": "r1",
                "hosts_yaml_etag": "h",
                "sap_parameters_yaml_etag": "p",
            }
        ).encode("utf-8")
        backend, _ = self._make_backend(data_dir, {}, {})
        with pytest.raises(WorkspaceConfigError, match="unsupported"):
            backend._parse_manifest(manifest, "WS-01")

    def test_parse_manifest_rejects_incomplete(self, data_dir: Path) -> None:
        """Raise WorkspaceConfigError when required manifest fields are empty."""
        manifest = json.dumps(
            {
                "schema_version": 1,
                "revision": "",
                "hosts_yaml_etag": "h",
                "sap_parameters_yaml_etag": "p",
            }
        ).encode("utf-8")
        backend, _ = self._make_backend(data_dir, {}, {})
        with pytest.raises(WorkspaceConfigError, match="incomplete"):
            backend._parse_manifest(manifest, "WS-01")

    def test_list_workspaces_discovers_valid_entries(self, data_dir: Path) -> None:
        """Return workspace entries for blob prefixes containing a valid manifest."""
        manifest = json.dumps(
            {
                "schema_version": 1,
                "revision": "r1",
                "hosts_yaml_etag": "hosts-v1",
                "sap_parameters_yaml_etag": "params-v1",
            }
        ).encode("utf-8")
        blobs = {
            f"PROD-WS/{WORKSPACE_MANIFEST_FILE}": manifest,
            "PROD-WS/hosts.yaml": b"all:\n  hosts:\n    node1:\n",
            "PROD-WS/sap-parameters.yaml": b"sap_sid: X01\n",
        }
        etags = {
            f"PROD-WS/{WORKSPACE_MANIFEST_FILE}": ["m-v1", "m-v1"],
            "PROD-WS/hosts.yaml": "hosts-v1",
            "PROD-WS/sap-parameters.yaml": "params-v1",
        }
        backend, _ = self._make_backend(data_dir, blobs, etags)
        workspaces = backend.list_workspaces()
        assert len(workspaces) == 1
        assert workspaces[0].workspace_id == "PROD-WS"

    def test_read_blob_bounded_rejects_oversized_properties(
        self, data_dir: Path, mocker: MockerFixture
    ) -> None:
        """Raise WorkspaceConfigError when blob properties report size exceeding the limit."""
        container = FakeContainerClient({}, {}, mock_factory=mocker.MagicMock)
        blob_client = mocker.MagicMock()
        blob_client.get_blob_properties.return_value = SimpleNamespace(
            size=MAX_CONFIG_FILE_SIZE + 1, etag="e1"
        )
        container.get_blob_client = mocker.MagicMock(return_value=blob_client)
        backend = BlobWorkspaceBackend(
            container_client=cast(ContainerClient, container),
            data_dir=data_dir,
        )
        with pytest.raises(WorkspaceConfigError, match="byte limit"):
            backend._read_blob_bounded("WS-01/hosts.yaml")

    def test_selects_filesystem_when_no_blob_endpoint(self, ws_base: Path) -> None:
        """Select filesystem backend when no AZURE_BLOB_ENDPOINT is configured."""
        backend = create_workspace_backend(env={}, workspaces_base=ws_base)
        assert isinstance(backend, FilesystemWorkspaceBackend)

    def test_requires_azure_context_for_blob_backend(self, mocker: MockerFixture) -> None:
        """Raise WorkspaceBackendError when blob endpoint is set but no Azure context provided."""
        with pytest.raises(WorkspaceBackendError, match="AzureStorageContext"):
            create_workspace_backend(
                env={"AZURE_BLOB_ENDPOINT": "https://acct.blob.core.windows.net"}
            )

    def test_uses_shared_container_client(self, data_dir: Path, mocker: MockerFixture) -> None:
        """Use the container client from the shared Azure context for the blob backend."""
        azure_context = mocker.MagicMock()
        azure_context.has_blob = True
        container = FakeContainerClient({}, {}, mock_factory=mocker.MagicMock)
        azure_context.get_container_client.return_value = container
        backend = create_workspace_backend(
            env={"AZURE_BLOB_ENDPOINT": "https://acct.blob.core.windows.net"},
            azure_context=azure_context,
            data_dir=data_dir,
        )
        assert isinstance(backend, BlobWorkspaceBackend)
        azure_context.get_container_client.assert_called_once()

    def test_whitespace_only_endpoint_uses_filesystem(self, ws_base: Path) -> None:
        """Treat whitespace-only AZURE_BLOB_ENDPOINT as absent and select filesystem."""
        backend = create_workspace_backend(
            env={"AZURE_BLOB_ENDPOINT": "   "},
            workspaces_base=ws_base,
        )
        assert isinstance(backend, FilesystemWorkspaceBackend)

    def test_azure_context_without_blob_raises(self, mocker: MockerFixture) -> None:
        """Raise WorkspaceBackendError when Azure context lacks blob service capability."""
        azure_context = mocker.MagicMock()
        azure_context.has_blob = False
        with pytest.raises(WorkspaceBackendError, match="AzureStorageContext"):
            create_workspace_backend(
                env={"AZURE_BLOB_ENDPOINT": "https://acct.blob.core.windows.net"},
                azure_context=azure_context,
            )

    def test_custom_container_name_from_env(self, data_dir: Path, mocker: MockerFixture) -> None:
        """Use the AZURE_BLOB_CONTAINER env var to select a custom container name."""
        azure_context = mocker.MagicMock()
        azure_context.has_blob = True
        container = FakeContainerClient({}, {}, mock_factory=mocker.MagicMock)
        azure_context.get_container_client.return_value = container
        create_workspace_backend(
            env={
                "AZURE_BLOB_ENDPOINT": "https://acct.blob.core.windows.net",
                "AZURE_BLOB_CONTAINER": "custom-container",
            },
            azure_context=azure_context,
            data_dir=data_dir,
        )
        azure_context.get_container_client.assert_called_once_with("custom-container")

    def test_config_extra_vars_are_deeply_immutable(self) -> None:
        """Verify WorkspaceConfig extra_vars are deeply frozen after construction."""
        source = {"nodes": [{"name": "node1"}]}
        config = WorkspaceConfig(
            workspace_id="TEST-WS",
            inventory_path="hosts.yaml",
            extra_vars=source,
        )
        source["nodes"][0]["name"] = "changed"
        assert config.extra_vars["nodes"][0]["name"] == "node1"
        with pytest.raises(TypeError):
            config.extra_vars["new"] = "value"  # type: ignore[index]
        with pytest.raises(TypeError):
            config.extra_vars["nodes"][0]["name"] = "value"  # type: ignore[index]

    def test_frozen_vars_thaw_to_native_ansible_values(self) -> None:
        """Thaw frozen extra_vars into a mutable dict without affecting the original."""
        config = WorkspaceConfig(
            workspace_id="TEST-WS",
            inventory_path="hosts.yaml",
            extra_vars={"nodes": [{"name": "node1"}]},
        )
        mutable = mutable_workspace_vars(config.extra_vars)
        mutable["nodes"][0]["name"] = "node2"
        assert mutable == {"nodes": [{"name": "node2"}]}
        assert config.extra_vars["nodes"][0]["name"] == "node1"

    def test_frozen_vars_preserve_nested_mapping_keys(self) -> None:
        """Preserve non-string nested keys while freezing and thawing variables."""
        config = WorkspaceConfig(
            workspace_id="TEST-WS",
            inventory_path="hosts.yaml",
            extra_vars={"priorities": {1: "primary", 2: "secondary"}},
        )

        mutable = mutable_workspace_vars(config.extra_vars)

        assert mutable["priorities"] == {1: "primary", 2: "secondary"}

    def test_materialized_workspace_extra_vars_are_frozen(self) -> None:
        """Verify MaterializedWorkspace extra_vars raise TypeError on mutation attempt."""
        materialized = MaterializedWorkspace(
            workspace_id="WS-01",
            job_id="d1c73be2-7d55-479d-8b97-2d63d5d032d8",
            local_path=Path("/tmp/test"),
            inventory_path="hosts.yaml",
            extra_vars={"key": "value"},
        )
        with pytest.raises(TypeError):
            materialized.extra_vars["key"] = "changed"  # type: ignore[index]
