# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for workspace backends and factory selection."""

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator, Mapping
import pytest
from azure.core.exceptions import ResourceNotFoundError
from pytest_mock import MockerFixture
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
def ws_base() -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td) / "WORKSPACES" / "SYSTEM"
        base.mkdir(parents=True)
        yield base


@pytest.fixture
def data_dir() -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def fs_backend(ws_base: Path, data_dir: Path) -> FilesystemWorkspaceBackend:
    return FilesystemWorkspaceBackend(workspaces_base=ws_base, data_dir=data_dir)


def _create_ws(
    base: Path, name: str, *, hosts: str = "all:\n  hosts:\n", params: str | None = None
) -> Path:
    workspace = base / name
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "hosts.yaml").write_text(hosts, encoding="utf-8")
    if params is not None:
        (workspace / "sap-parameters.yaml").write_text(params, encoding="utf-8")
    return workspace


class FakeBlobClient:
    def __init__(self, name: str, data: bytes, etag_source) -> None:
        self.name = name
        self._data = data
        self._etag_source = etag_source

    def get_blob_properties(self):
        etag = self._etag_source()
        return SimpleNamespace(size=len(self._data), etag=etag)

    def download_blob(self, **kwargs):
        expected_etag = kwargs.get("etag")
        current_etag = self._etag_source()
        if expected_etag is not None and expected_etag != current_etag:
            from azure.core.exceptions import ResourceModifiedError

            raise ResourceModifiedError("etag changed")
        return SimpleNamespace(readall=lambda: self._data)


class FakeMissingBlobClient:
    """Blob client that consistently reports a missing blob."""

    def get_blob_properties(self) -> None:
        raise ResourceNotFoundError("missing")

    def download_blob(self, **_kwargs: Any) -> None:
        raise ResourceNotFoundError("missing")


class FakeContainerClient:
    def __init__(self, blobs: dict[str, bytes], etags: Mapping[str, list[str] | str]) -> None:
        self._blobs = blobs
        self._etags = dict(etags)
        self._counters = {name: 0 for name in etags}
        self.closed = False

    def list_blobs(self, name_starts_with: str = "", **kwargs):
        return [
            SimpleNamespace(name=name) for name in self._blobs if name.startswith(name_starts_with)
        ]

    def walk_blobs(self, delimiter: str = "/", **kwargs):
        prefixes = sorted({name.split("/")[0] + "/" for name in self._blobs if "/" in name})
        return [SimpleNamespace(name=prefix) for prefix in prefixes]

    def get_blob_client(self, blob: str):
        if blob not in self._blobs:
            return FakeMissingBlobClient()

        def current_etag() -> str:
            values = self._etags.get(blob, "etag-default")
            if isinstance(values, list):
                index = self._counters[blob]
                self._counters[blob] = min(index + 1, len(values) - 1)
                return values[index]
            return values

        return FakeBlobClient(blob, self._blobs[blob], current_etag)

    def close(self) -> None:
        self.closed = True


class TestWorkspaceBackend:
    def test_validate_workspace_id_accepts_valid_values(self) -> None:
        assert validate_workspace_id("DEV-EUS2-SAP01") == "DEV-EUS2-SAP01"

    def test_validate_workspace_id_rejects_invalid_values(self) -> None:
        for workspace_id in ("", "../etc", "foo/bar", ".hidden"):
            with pytest.raises(WorkspaceValidationError):
                validate_workspace_id(workspace_id)

    def test_parse_hosts_yaml_requires_non_empty_mapping(self) -> None:
        with pytest.raises(WorkspaceConfigError, match="mapping"):
            parse_hosts_yaml(b"- item")
        with pytest.raises(WorkspaceConfigError, match="must not be empty"):
            parse_hosts_yaml(b"{}")

    def test_parse_sap_parameters_requires_mapping(self) -> None:
        with pytest.raises(WorkspaceConfigError, match="mapping"):
            parse_sap_parameters(b"- item")

    def test_get_workspace_config(
        self, ws_base: Path, fs_backend: FilesystemWorkspaceBackend
    ) -> None:
        _create_ws(ws_base, "DEV-WS-01", params="sap_sid: HDB\ndatabase_high_availability: true\n")
        config = fs_backend.get_workspace_config("DEV-WS-01")
        assert config.sap_sid == "HDB"
        assert config.database_high_availability is True

    def test_materialize_requires_sap_parameters(
        self, ws_base: Path, fs_backend: FilesystemWorkspaceBackend
    ) -> None:
        _create_ws(ws_base, "DEV-WS-01")
        with pytest.raises(WorkspaceConfigError, match="sap-parameters.yaml missing"):
            fs_backend.materialize("DEV-WS-01", "d1c73be2-7d55-479d-8b97-2d63d5d032d8")

    def test_materialize_rejects_non_uuid_job_id(
        self, ws_base: Path, fs_backend: FilesystemWorkspaceBackend
    ) -> None:
        _create_ws(ws_base, "DEV-WS-01", params="sap_sid: HDB\n")
        with pytest.raises(WorkspaceValidationError, match="UUID"):
            fs_backend.materialize("DEV-WS-01", "job-123")

    def test_symlink_escape_is_rejected(
        self, ws_base: Path, fs_backend: FilesystemWorkspaceBackend
    ) -> None:
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
        workspace = _create_ws(ws_base, "BIG-WS", params="sap_sid: HDB\n")
        hosts_file = workspace / "hosts.yaml"
        hosts_file.write_bytes(b"x" * (MAX_CONFIG_FILE_SIZE + 1))
        with pytest.raises(WorkspaceConfigError, match="byte limit"):
            fs_backend.get_workspace_config("BIG-WS")

    def test_cleanup_not_owned_is_noop(
        self, ws_base: Path, fs_backend: FilesystemWorkspaceBackend
    ) -> None:
        _create_ws(ws_base, "DEV-WS-01", params="sap_sid: HDB\n")
        materialized = fs_backend.materialize("DEV-WS-01", "d1c73be2-7d55-479d-8b97-2d63d5d032d8")
        fs_backend.cleanup(materialized)
        assert materialized.local_path.exists()

    def test_list_workspaces_skips_missing_params(
        self, ws_base: Path, fs_backend: FilesystemWorkspaceBackend
    ) -> None:
        _create_ws(ws_base, "HOSTS-ONLY")
        assert fs_backend.list_workspaces() == []

    def test_list_workspaces_skips_malformed_hosts(
        self, ws_base: Path, fs_backend: FilesystemWorkspaceBackend
    ) -> None:
        _create_ws(ws_base, "BAD-HOSTS", hosts="- bad", params="sap_sid: HDB\n")
        assert fs_backend.list_workspaces() == []

    def _make_backend(
        self,
        data_dir: Path,
        blobs: dict[str, bytes],
        etags: Mapping[str, list[str] | str],
    ) -> tuple[BlobWorkspaceBackend, FakeContainerClient]:
        container = FakeContainerClient(blobs, etags)
        return BlobWorkspaceBackend(container_client=container, data_dir=data_dir), container

    def test_get_workspace_config_uses_manifest_revision(self, data_dir: Path) -> None:
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

    def test_missing_manifest_for_existing_workspace_is_config_error(self, data_dir: Path) -> None:
        blobs = {
            "WS-01/hosts.yaml": b"all:\n  hosts:\n",
            "WS-01/sap-parameters.yaml": b"sap_sid: HDB\n",
        }
        etags = {"WS-01/hosts.yaml": "hosts-v1", "WS-01/sap-parameters.yaml": "params-v1"}
        backend, _ = self._make_backend(data_dir, blobs, etags)
        with pytest.raises(WorkspaceConfigError, match=WORKSPACE_MANIFEST_FILE):
            backend.get_workspace_config("WS-01")

    def test_materialize_builds_atomic_directory(self, data_dir: Path) -> None:
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
        backend, _ = self._make_backend(data_dir, {}, {})
        with pytest.raises(WorkspaceValidationError, match="UUID"):
            backend.materialize("WS-01", "job-123")

    def test_materialize_rejects_preexisting_target(self, data_dir: Path) -> None:
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

    def test_cleanup_removes_owned_directory(self, data_dir: Path) -> None:
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
            container_client=FakeContainerClient({}, {}), data_dir=data_dir
        ).cleanup(materialized)
        assert not materialized.local_path.exists()

    def test_close_is_noop_for_non_owning_container(self, data_dir: Path) -> None:
        backend, container = self._make_backend(data_dir, {}, {})
        backend.close()
        assert container.closed is False

    def test_read_blob_bounded_wraps_type_error_as_backend_error(
        self, data_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        container = FakeContainerClient({}, {})

        def fail_download(**_kwargs: Any) -> None:
            raise TypeError("unsupported etag kwargs")

        blob_client = SimpleNamespace(
            get_blob_properties=lambda: SimpleNamespace(size=1, etag="etag-v1"),
            download_blob=fail_download,
        )
        monkeypatch.setattr(container, "get_blob_client", lambda _name: blob_client)
        backend = BlobWorkspaceBackend(container_client=container, data_dir=data_dir)

        with pytest.raises(WorkspaceBackendError, match="Failed to read blob"):
            backend._read_blob_bounded("WS-01/hosts.yaml", expected_etag="etag-v1")

    def test_read_blob_bounded_rejects_stale_oversized_download(
        self, data_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        container = FakeContainerClient({}, {})
        blob_client = SimpleNamespace(
            get_blob_properties=lambda: SimpleNamespace(
                size=MAX_CONFIG_FILE_SIZE - 1,
                etag="etag-v1",
            ),
            download_blob=lambda **_kwargs: SimpleNamespace(
                readall=lambda: b"x" * (MAX_CONFIG_FILE_SIZE + 1)
            ),
        )
        monkeypatch.setattr(container, "get_blob_client", lambda _name: blob_client)
        backend = BlobWorkspaceBackend(container_client=container, data_dir=data_dir)

        with pytest.raises(WorkspaceConfigError, match="byte limit"):
            backend._read_blob_bounded("WS-01/hosts.yaml", expected_etag="etag-v1")

    def test_selects_filesystem_when_no_blob_endpoint(self, ws_base: Path) -> None:
        backend = create_workspace_backend(env={}, workspaces_base=ws_base)
        assert isinstance(backend, FilesystemWorkspaceBackend)

    def test_requires_azure_context_for_blob_backend(self) -> None:
        with pytest.raises(WorkspaceBackendError, match="AzureStorageContext"):
            create_workspace_backend(
                env={"AZURE_BLOB_ENDPOINT": "https://acct.blob.core.windows.net"}
            )

    def test_uses_shared_container_client(self, data_dir: Path, mocker: MockerFixture) -> None:
        azure_context = mocker.MagicMock()
        azure_context.has_blob = True
        container = FakeContainerClient({}, {})
        azure_context.get_container_client.return_value = container
        backend = create_workspace_backend(
            env={"AZURE_BLOB_ENDPOINT": "https://acct.blob.core.windows.net"},
            azure_context=azure_context,
            data_dir=data_dir,
        )
        assert isinstance(backend, BlobWorkspaceBackend)
        azure_context.get_container_client.assert_called_once()

    def test_config_extra_vars_are_deeply_immutable(self) -> None:
        source = {"nodes": [{"name": "node1"}]}
        config = WorkspaceConfig(
            workspace_id="TEST-WS",
            inventory_path="hosts.yaml",
            extra_vars=source,
        )
        source["nodes"][0]["name"] = "changed"

        assert config.extra_vars["nodes"][0]["name"] == "node1"
        assert not hasattr(config.extra_vars, "__setitem__")
        assert not hasattr(config.extra_vars["nodes"][0], "__setitem__")

    def test_frozen_vars_thaw_to_native_ansible_values(self) -> None:
        config = WorkspaceConfig(
            workspace_id="TEST-WS",
            inventory_path="hosts.yaml",
            extra_vars={"nodes": [{"name": "node1"}]},
        )

        mutable = mutable_workspace_vars(config.extra_vars)
        mutable["nodes"][0]["name"] = "node2"

        assert mutable == {"nodes": [{"name": "node2"}]}
        assert config.extra_vars["nodes"][0]["name"] == "node1"
