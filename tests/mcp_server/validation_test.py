# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the InputValidator class."""

from __future__ import annotations
from pathlib import Path
from pytest_mock import MockerFixture
import pytest
from mcp.server.fastmcp.exceptions import ToolError
from src.mcp_server.validation import (
    MAX_DEFINITIONS_COUNT,
    MAX_QUERY_LENGTH,
    MAX_TIMEOUT,
    MIN_TIMEOUT,
    InputValidator,
)


@pytest.fixture()
def validator(tmp_path: Path, mocker: MockerFixture) -> InputValidator:
    """Build an InputValidator backed by *tmp_path* as the workspace root."""
    return InputValidator(
        workspaces_base=tmp_path,
        sessions={},
        job_store=mocker.MagicMock(),
    )


class TestWorkspaceId:

    def test_valid_id(self, tmp_path: Path, validator: InputValidator):
        (tmp_path / "WS_A").mkdir()
        validator.workspace_id("WS_A")  # should not raise

    def test_empty_id_raises(self, validator: InputValidator):
        with pytest.raises(ToolError, match="required"):
            validator.workspace_id("")

    def test_invalid_chars_raises(self, validator: InputValidator):
        with pytest.raises(ToolError, match="Invalid workspace_id"):
            validator.workspace_id("../../etc")

    def test_slash_in_id_raises(self, validator: InputValidator):
        with pytest.raises(ToolError, match="Invalid workspace_id"):
            validator.workspace_id("foo/bar")

    def test_starts_with_dot_raises(self, validator: InputValidator):
        with pytest.raises(ToolError, match="Invalid workspace_id"):
            validator.workspace_id(".hidden")

    def test_starts_with_hyphen_raises(self, validator: InputValidator):
        with pytest.raises(ToolError, match="Invalid workspace_id"):
            validator.workspace_id("-bad")

    def test_nonexistent_workspace_raises(self, validator: InputValidator):
        with pytest.raises(ToolError, match="not found"):
            validator.workspace_id("MISSING")

    def test_dots_and_hyphens_allowed(self, tmp_path: Path, validator: InputValidator):
        (tmp_path / "my-workspace.v2").mkdir()
        validator.workspace_id("my-workspace.v2")

    def test_path_traversal_blocked(self, validator: InputValidator):
        with pytest.raises(ToolError):
            validator.workspace_id("..%2F..%2Fetc")

    def test_max_length_id(self, tmp_path: Path, validator: InputValidator):
        long_id = "A" * 128
        (tmp_path / long_id).mkdir()
        validator.workspace_id(long_id)

    def test_over_max_length_raises(self, validator: InputValidator):
        with pytest.raises(ToolError, match="Invalid workspace_id"):
            validator.workspace_id("A" * 129)


class TestQuery:

    def test_valid_query(self, validator: InputValidator):
        assert validator.query("HANA cluster status") == "HANA cluster status"

    def test_strips_whitespace(self, validator: InputValidator):
        assert validator.query("  trimmed  ") == "trimmed"

    def test_empty_raises(self, validator: InputValidator):
        with pytest.raises(ToolError, match="required"):
            validator.query("")

    def test_whitespace_only_raises(self, validator: InputValidator):
        with pytest.raises(ToolError, match="required"):
            validator.query("   ")

    def test_too_long_raises(self, validator: InputValidator):
        with pytest.raises(ToolError, match="maximum length"):
            validator.query("x" * (MAX_QUERY_LENGTH + 1))

    def test_exactly_max_length(self, validator: InputValidator):
        assert len(validator.query("x" * MAX_QUERY_LENGTH)) == MAX_QUERY_LENGTH


class TestTimeout:

    def test_valid_timeout(self, validator: InputValidator):
        assert validator.timeout(30) == 30

    def test_min_boundary(self, validator: InputValidator):
        assert validator.timeout(MIN_TIMEOUT) == MIN_TIMEOUT

    def test_max_boundary(self, validator: InputValidator):
        assert validator.timeout(MAX_TIMEOUT) == MAX_TIMEOUT

    def test_below_min_raises(self, validator: InputValidator):
        with pytest.raises(ToolError, match="between"):
            validator.timeout(MIN_TIMEOUT - 1)

    def test_above_max_raises(self, validator: InputValidator):
        with pytest.raises(ToolError, match="between"):
            validator.timeout(MAX_TIMEOUT + 1)


class TestDefinitions:

    def test_none_returns_none(self, validator: InputValidator):
        assert validator.definitions(None) is None

    def test_valid_list(self, validator: InputValidator):
        ids = ["cluster-status", "hana-topology"]
        assert validator.definitions(ids) == ids

    def test_too_many_raises(self, validator: InputValidator):
        ids = [f"def-{i}" for i in range(MAX_DEFINITIONS_COUNT + 1)]
        with pytest.raises(ToolError, match="Too many"):
            validator.definitions(ids)

    def test_empty_id_raises(self, validator: InputValidator):
        with pytest.raises(ToolError, match="Invalid definition ID"):
            validator.definitions([""])

    def test_too_long_id_raises(self, mocker: MockerFixture, validator: InputValidator):
        with pytest.raises(ToolError, match="Invalid definition ID"):
            validator.definitions(["x" * 129])

    def test_exactly_max_count(self, mocker: MockerFixture, validator: InputValidator):
        ids = [f"def-{i}" for i in range(MAX_DEFINITIONS_COUNT)]
        assert validator.definitions(ids) == ids


class TestSessionId:

    def test_valid_session(self, mocker: MockerFixture, tmp_path: Path):
        v = InputValidator(tmp_path, sessions={"s1": "session_obj"}, job_store=mocker.MagicMock())
        assert v.session_id("s1") == "session_obj"

    def test_empty_raises(self, mocker: MockerFixture, validator: InputValidator):
        with pytest.raises(ToolError, match="required"):
            validator.session_id("")

    def test_missing_raises(self, mocker: MockerFixture, tmp_path: Path):
        v = InputValidator(tmp_path, sessions={"other": "val"}, job_store=mocker.MagicMock())
        with pytest.raises(ToolError, match="not found"):
            v.session_id("missing")


class TestJobId:

    def test_valid_job(self, mocker: MockerFixture, tmp_path: Path):
        store = mocker.MagicMock()
        store.get.return_value = "job_obj"
        v = InputValidator(tmp_path, sessions={}, job_store=store)
        assert v.job_id("j1") == "job_obj"
        store.get.assert_called_once_with("j1")

    def test_empty_raises(self, mocker: MockerFixture, validator: InputValidator):
        with pytest.raises(ToolError, match="required"):
            validator.job_id("")

    def test_not_found_raises(self, mocker: MockerFixture, tmp_path: Path):
        store = mocker.MagicMock()
        store.get.return_value = None
        v = InputValidator(tmp_path, sessions={}, job_store=store)
        with pytest.raises(ToolError, match="not found"):
            v.job_id("missing")
