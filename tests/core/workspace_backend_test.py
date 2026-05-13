# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for workspace backend implementations."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Generator, List, Optional
from unittest.mock import MagicMock, patch

import pytest
import yaml

from src.core.models.workspace import WorkspaceInfo
from src.core.services.workspace_backend import (
    BlobBackend,
    FilesystemBackend,
    WorkspaceBackend,
    create_workspace_backend,
)
from src.core.services.workspace_discovery import (
    get_workspace_backend,
    load_workspaces_from_directory,
    set_workspace_backend,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_workspace(
    base: Path,
    name: str,
    *,
    sap_sid: str = "HDB",
    hosts: bool = True,
    params: bool = True,
) -> Path:
    """Create a minimal workspace directory with config files."""
    ws = base / name
    ws.mkdir(parents=True, exist_ok=True)
    if hosts:
        (ws / "hosts.yaml").write_text("all:\n  hosts:\n    node1:\n      ansible_host: 10.0.0.1\n")
    if params:
        (ws / "sap-parameters.yaml").write_text(f"sap_sid: {sap_sid}\n")
    return ws


# ---------------------------------------------------------------------------
# FilesystemBackend tests
# ---------------------------------------------------------------------------


class TestFilesystemBackend:
    """Tests for :class:`FilesystemBackend`."""

    def test_list_empty_directory(self, tmp_path: Path) -> None:
        """Returns empty list when no workspaces exist."""
        backend = FilesystemBackend(base_dir=str(tmp_path))
        assert backend.list_workspaces() == []

    def test_list_nonexistent_directory(self) -> None:
        """Returns empty list when base directory does not exist."""
        backend = FilesystemBackend(base_dir="/nonexistent/path")
        assert backend.list_workspaces() == []

    def test_list_skips_hidden(self, tmp_path: Path) -> None:
        """Skips directories starting with a dot."""
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        (hidden / "hosts.yaml").write_text("all:\n")
        backend = FilesystemBackend(base_dir=str(tmp_path))
        assert backend.list_workspaces() == []

    def test_list_skips_no_config(self, tmp_path: Path) -> None:
        """Skips directories without hosts.yaml or sap-parameters.yaml."""
        (tmp_path / "EMPTY-WS").mkdir()
        backend = FilesystemBackend(base_dir=str(tmp_path))
        assert backend.list_workspaces() == []

    def test_list_workspace_with_params(self, tmp_path: Path) -> None:
        """Discovers workspace with sap-parameters.yaml."""
        _create_workspace(tmp_path, "DEV-EUS2-SAP01", sap_sid="HDB")
        backend = FilesystemBackend(base_dir=str(tmp_path))
        result = backend.list_workspaces()
        assert len(result) == 1
        assert result[0].id == "DEV-EUS2-SAP01"
        assert result[0].name == "HDB"
        assert result[0].environment == "DEV"
        assert result[0].config_exists is True

    def test_list_workspace_without_params(self, tmp_path: Path) -> None:
        """Discovers workspace with only hosts.yaml."""
        _create_workspace(tmp_path, "NOPARAM-WS", params=False)
        backend = FilesystemBackend(base_dir=str(tmp_path))
        result = backend.list_workspaces()
        assert len(result) == 1
        assert result[0].name == "NOPARAM-WS"
        assert result[0].config_exists is False

    def test_list_no_hyphen_in_name(self, tmp_path: Path) -> None:
        """Environment is empty when workspace name has no hyphen."""
        _create_workspace(tmp_path, "STANDALONE", sap_sid="S4H")
        backend = FilesystemBackend(base_dir=str(tmp_path))
        result = backend.list_workspaces()
        assert result[0].environment == ""

    def test_list_invalid_yaml(self, tmp_path: Path) -> None:
        """Handles invalid YAML gracefully."""
        ws = tmp_path / "BAD-YAML"
        ws.mkdir()
        (ws / "hosts.yaml").write_text("all:\n")
        (ws / "sap-parameters.yaml").write_text(": invalid: yaml: [[[")
        backend = FilesystemBackend(base_dir=str(tmp_path))
        result = backend.list_workspaces()
        assert len(result) == 1
        assert result[0].id == "BAD-YAML"

    def test_list_multiple_workspaces(self, tmp_path: Path) -> None:
        """Discovers multiple workspaces."""
        _create_workspace(tmp_path, "PRD-WS-01", sap_sid="HDB")
        _create_workspace(tmp_path, "DEV-WS-02", sap_sid="S4H")
        backend = FilesystemBackend(base_dir=str(tmp_path))
        result = backend.list_workspaces()
        assert len(result) == 2
        ids = {ws.id for ws in result}
        assert ids == {"PRD-WS-01", "DEV-WS-02"}

    def test_read_file_exists(self, tmp_path: Path) -> None:
        """Reads an existing file."""
        _create_workspace(tmp_path, "WS1")
        backend = FilesystemBackend(base_dir=str(tmp_path))
        content = backend.read_file("WS1", "sap-parameters.yaml")
        assert content is not None
        assert "sap_sid" in content

    def test_read_file_missing(self, tmp_path: Path) -> None:
        """Returns None for a missing file."""
        (tmp_path / "WS1").mkdir()
        backend = FilesystemBackend(base_dir=str(tmp_path))
        assert backend.read_file("WS1", "missing.yaml") is None

    def test_read_yaml(self, tmp_path: Path) -> None:
        """Parses YAML content correctly."""
        _create_workspace(tmp_path, "WS1", sap_sid="HA1")
        backend = FilesystemBackend(base_dir=str(tmp_path))
        data = backend.read_yaml("WS1", "sap-parameters.yaml")
        assert data["sap_sid"] == "HA1"

    def test_read_yaml_missing(self, tmp_path: Path) -> None:
        """Returns empty dict for missing YAML file."""
        (tmp_path / "WS1").mkdir()
        backend = FilesystemBackend(base_dir=str(tmp_path))
        assert backend.read_yaml("WS1", "nope.yaml") == {}

    def test_file_exists_true(self, tmp_path: Path) -> None:
        """Returns True for existing file."""
        _create_workspace(tmp_path, "WS1")
        backend = FilesystemBackend(base_dir=str(tmp_path))
        assert backend.file_exists("WS1", "hosts.yaml") is True

    def test_file_exists_false(self, tmp_path: Path) -> None:
        """Returns False for missing file."""
        (tmp_path / "WS1").mkdir()
        backend = FilesystemBackend(base_dir=str(tmp_path))
        assert backend.file_exists("WS1", "nope.yaml") is False

    def test_workspace_path(self, tmp_path: Path) -> None:
        """Returns the correct local path."""
        backend = FilesystemBackend(base_dir=str(tmp_path))
        assert backend.workspace_path("WS1") == str(tmp_path / "WS1")


# ---------------------------------------------------------------------------
# BlobBackend tests (mocked Azure SDK)
# ---------------------------------------------------------------------------


class _FakeBlob:
    """Minimal blob descriptor for mocked list_blobs."""

    def __init__(self, name: str) -> None:
        self.name = name


class TestBlobBackend:
    """Tests for :class:`BlobBackend` with mocked Azure clients."""

    @pytest.fixture(autouse=True)
    def _patch_azure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Patch Azure SDK imports so BlobBackend can be instantiated."""
        self.mock_container = MagicMock()
        self.mock_credential = MagicMock()
        container_ref = self.mock_container
        credential_ref = self.mock_credential

        def _patched_init(self_bb: Any, **kwargs: Any) -> None:
            self_bb._client = container_ref
            self_bb._credential = credential_ref
            self_bb._account_url = kwargs.get(
                "account_url",
                "https://test.blob.core.windows.net",
            )
            self_bb._container_name = kwargs.get("container_name", "workspaces")

        monkeypatch.setattr(
            "src.core.services.workspace_backend." "BlobBackend.__init__",
            _patched_init,
        )

    def _make_backend(self) -> BlobBackend:
        return BlobBackend(
            account_url="https://test.blob.core.windows.net",
            container_name="workspaces",
        )

    def test_list_workspaces_basic(self) -> None:
        """Discovers workspaces from blob listing."""
        self.mock_container.list_blobs.return_value = [
            _FakeBlob("DEV-WS/hosts.yaml"),
            _FakeBlob("DEV-WS/sap-parameters.yaml"),
            _FakeBlob("PRD-WS/hosts.yaml"),
        ]

        mock_blob_client = MagicMock()
        mock_blob_client.download_blob.return_value.readall.return_value = b"sap_sid: HA1\n"
        self.mock_container.get_blob_client.return_value = mock_blob_client

        backend = self._make_backend()
        result = backend.list_workspaces()
        assert len(result) == 2
        ids = {ws.id for ws in result}
        assert "DEV-WS" in ids
        assert "PRD-WS" in ids

    def test_list_workspaces_skips_hidden(self) -> None:
        """Skips blob prefixes starting with a dot."""
        self.mock_container.list_blobs.return_value = [
            _FakeBlob(".hidden/hosts.yaml"),
        ]
        backend = self._make_backend()
        assert backend.list_workspaces() == []

    def test_list_workspaces_skips_no_config(self) -> None:
        """Skips prefixes without hosts.yaml or sap-parameters.yaml."""
        self.mock_container.list_blobs.return_value = [
            _FakeBlob("WS/readme.md"),
        ]
        backend = self._make_backend()
        assert backend.list_workspaces() == []

    def test_list_workspaces_skips_root_blobs(self) -> None:
        """Ignores blobs that are not under a prefix."""
        self.mock_container.list_blobs.return_value = [
            _FakeBlob("root-file.txt"),
        ]
        backend = self._make_backend()
        assert backend.list_workspaces() == []

    def test_read_file_success(self) -> None:
        """Reads blob content as a string."""
        mock_blob_client = MagicMock()
        mock_blob_client.download_blob.return_value.readall.return_value = b"sap_sid: HA1\n"
        self.mock_container.get_blob_client.return_value = mock_blob_client

        backend = self._make_backend()
        content = backend.read_file("WS1", "sap-parameters.yaml")
        assert content == "sap_sid: HA1\n"
        self.mock_container.get_blob_client.assert_called_with("WS1/sap-parameters.yaml")

    def test_read_file_not_found(self) -> None:
        """Returns None when blob does not exist."""
        mock_blob_client = MagicMock()
        mock_blob_client.download_blob.side_effect = Exception("404")
        self.mock_container.get_blob_client.return_value = mock_blob_client

        backend = self._make_backend()
        assert backend.read_file("WS1", "missing.yaml") is None

    def test_read_yaml_success(self) -> None:
        """Parses YAML from blob content."""
        mock_blob_client = MagicMock()
        mock_blob_client.download_blob.return_value.readall.return_value = (
            b"sap_sid: HA2\nplatform: HANA\n"
        )
        self.mock_container.get_blob_client.return_value = mock_blob_client

        backend = self._make_backend()
        data = backend.read_yaml("WS1", "sap-parameters.yaml")
        assert data["sap_sid"] == "HA2"
        assert data["platform"] == "HANA"

    def test_read_yaml_missing(self) -> None:
        """Returns empty dict for missing YAML blob."""
        mock_blob_client = MagicMock()
        mock_blob_client.download_blob.side_effect = Exception("404")
        self.mock_container.get_blob_client.return_value = mock_blob_client

        backend = self._make_backend()
        assert backend.read_yaml("WS1", "nope.yaml") == {}

    def test_file_exists_true(self) -> None:
        """Returns True when blob exists."""
        mock_blob_client = MagicMock()
        mock_blob_client.get_blob_properties.return_value = {}
        self.mock_container.get_blob_client.return_value = mock_blob_client

        backend = self._make_backend()
        assert backend.file_exists("WS1", "hosts.yaml") is True

    def test_file_exists_false(self) -> None:
        """Returns False when blob does not exist."""
        mock_blob_client = MagicMock()
        mock_blob_client.get_blob_properties.side_effect = Exception("404")
        self.mock_container.get_blob_client.return_value = mock_blob_client

        backend = self._make_backend()
        assert backend.file_exists("WS1", "missing.yaml") is False

    def test_workspace_path(self) -> None:
        """Returns the blob URL for a workspace prefix."""
        backend = self._make_backend()
        assert backend.workspace_path("WS1") == (
            "https://test.blob.core.windows.net/workspaces/WS1"
        )


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------


class TestCreateWorkspaceBackend:
    """Tests for :func:`create_workspace_backend`."""

    def test_default_is_filesystem(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Defaults to FilesystemBackend when BLOB_ACCOUNT_URL is not set."""
        monkeypatch.delenv("BLOB_ACCOUNT_URL", raising=False)
        monkeypatch.delenv("WORKSPACES_BASE", raising=False)
        backend = create_workspace_backend()
        assert isinstance(backend, FilesystemBackend)

    def test_explicit_filesystem(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Creates FilesystemBackend when BLOB_ACCOUNT_URL is absent."""
        monkeypatch.delenv("BLOB_ACCOUNT_URL", raising=False)
        monkeypatch.setenv("WORKSPACES_BASE", str(tmp_path))
        backend = create_workspace_backend()
        assert isinstance(backend, FilesystemBackend)

    def test_blob_with_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Creates BlobBackend when BLOB_ACCOUNT_URL is set."""
        monkeypatch.setenv(
            "BLOB_ACCOUNT_URL",
            "https://test.blob.core.windows.net",
        )
        monkeypatch.setenv("BLOB_CONTAINER_NAME", "my-container")

        with patch(
            "src.core.services.workspace_backend.BlobBackend.__init__",
            return_value=None,
        ) as mock_init:
            backend = create_workspace_backend()
            assert isinstance(backend, BlobBackend)
            mock_init.assert_called_once_with(
                account_url="https://test.blob.core.windows.net",
                container_name="my-container",
            )


# ---------------------------------------------------------------------------
# Workspace discovery integration tests
# ---------------------------------------------------------------------------


class TestWorkspaceDiscovery:
    """Tests for the discovery module singleton and delegation."""

    @pytest.fixture(autouse=True)
    def _reset_backend(self) -> Generator[None, None, None]:
        """Reset the singleton backend before each test."""
        set_workspace_backend(None)  # type: ignore[arg-type]
        yield
        set_workspace_backend(None)  # type: ignore[arg-type]

    def test_set_and_get_backend(self, tmp_path: Path) -> None:
        """set_workspace_backend overrides the singleton."""
        custom = FilesystemBackend(base_dir=str(tmp_path))
        set_workspace_backend(custom)
        assert get_workspace_backend() is custom

    def test_load_workspaces_delegates(self, tmp_path: Path) -> None:
        """load_workspaces_from_directory delegates to the backend."""
        _create_workspace(tmp_path, "WS-TEST", sap_sid="TST")
        backend = FilesystemBackend(base_dir=str(tmp_path))
        set_workspace_backend(backend)

        result = load_workspaces_from_directory(str(tmp_path))
        assert len(result) == 1
        assert result[0].id == "WS-TEST"

    def test_lazy_init(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Backend is lazily created on first get call."""
        monkeypatch.delenv("BLOB_ACCOUNT_URL", raising=False)
        monkeypatch.setenv("WORKSPACES_BASE", str(tmp_path))
        backend = get_workspace_backend()
        assert isinstance(backend, FilesystemBackend)


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    """Verify both backends satisfy the WorkspaceBackend protocol."""

    def test_filesystem_satisfies_protocol(self, tmp_path: Path) -> None:
        """FilesystemBackend is structurally compatible."""
        backend: WorkspaceBackend = FilesystemBackend(base_dir=str(tmp_path))
        assert hasattr(backend, "list_workspaces")
        assert hasattr(backend, "read_file")
        assert hasattr(backend, "read_yaml")
        assert hasattr(backend, "file_exists")
        assert hasattr(backend, "workspace_path")
