# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the STAF test skill."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from src.agents.skills.staf_test import (
    _TERMINAL_STATUSES,
    _TEST_CATALOG,
    _fetch_job_details,
    _fetch_job_log,
    _poll_job,
    build_staf_test_skill,
)


def _make_sap_context() -> MagicMock:
    ctx = MagicMock()
    ctx.core_api_url = "http://localhost:8000"
    return ctx


class TestTestCatalog:
    """Test catalog resource validation."""

    def test_catalog_has_three_groups(self) -> None:
        assert len(_TEST_CATALOG) == 3
        assert "DatabaseHighAvailability" in _TEST_CATALOG
        assert "SCSHighAvailability" in _TEST_CATALOG
        assert "ConfigurationChecks" in _TEST_CATALOG

    def test_catalog_entries_are_triples(self) -> None:
        for group, tests in _TEST_CATALOG.items():
            for entry in tests:
                assert len(entry) == 3, f"Bad entry in {group}: {entry}"
                assert isinstance(entry[0], str)
                assert isinstance(entry[1], str)
                assert isinstance(entry[2], bool)


class TestBuildStafTestSkill:
    """Tests for build_staf_test_skill factory."""

    def test_skill_metadata(self) -> None:
        skill = build_staf_test_skill(_make_sap_context())
        assert skill.name == "sap-staf-test"
        assert skill.description
        assert skill.content
        assert len(skill.resources) == 1
        assert len(skill.scripts) == 1

    def test_test_catalog_resource(self) -> None:
        skill = build_staf_test_skill(_make_sap_context())
        resource = skill.resources[0]
        result = resource.function()
        assert "DatabaseHighAvailability" in result
        assert "ha-config" in result
        assert "Destructive" in result


class TestRunTestScript:
    """Tests for the run_test script."""

    @pytest.mark.asyncio
    async def test_invalid_test_group(self) -> None:
        skill = build_staf_test_skill(_make_sap_context())
        script_fn = skill.scripts[0].function
        result = await script_fn(
            workspace_id="ws-1",
            test_group="InvalidGroup",
        )
        parsed = json.loads(result)
        assert parsed["status"] == "failed"
        assert "Unknown test_group" in parsed["error"]

    @pytest.mark.asyncio
    async def test_submit_failure(self, mocker: Any) -> None:
        ctx = _make_sap_context()
        skill = build_staf_test_skill(ctx)
        script_fn = skill.scripts[0].function

        mocker.patch(
            "src.agents.skills.staf_test.httpx.AsyncClient",
            side_effect=httpx.ConnectError("Connection refused"),
        )
        result = await script_fn(
            workspace_id="ws-1",
            test_group="ConfigurationChecks",
        )
        parsed = json.loads(result)
        assert parsed["status"] == "failed"
        assert "duration_ms" in parsed

    @pytest.mark.asyncio
    async def test_successful_run(self, mocker: Any) -> None:
        """Full happy path with mocked HTTP."""
        ctx = _make_sap_context()
        skill = build_staf_test_skill(ctx)
        script_fn = skill.scripts[0].function

        mock_client = mocker.AsyncMock()
        mock_response_submit = mocker.MagicMock()
        mock_response_submit.json.return_value = {"id": "job-123"}
        mock_response_submit.raise_for_status = mocker.MagicMock()

        mock_response_poll = mocker.MagicMock()
        mock_response_poll.json.return_value = {"status": "completed"}
        mock_response_poll.raise_for_status = mocker.MagicMock()

        mock_response_details = mocker.MagicMock()
        mock_response_details.json.return_value = {
            "status": "completed",
            "test_results": [{"test_id": "ha-config", "status": "passed"}],
        }
        mock_response_details.raise_for_status = mocker.MagicMock()

        mock_response_log = mocker.MagicMock()
        mock_response_log.text = "PLAY RECAP\nok=5 changed=0 failed=0"
        mock_response_log.raise_for_status = mocker.MagicMock()

        # Mock _poll_job and _fetch helpers to avoid real HTTP
        mocker.patch(
            "src.agents.skills.staf_test._poll_job",
            return_value="completed",
        )
        mocker.patch(
            "src.agents.skills.staf_test._fetch_job_details",
            return_value={
                "status": "completed",
                "test_results": [{"test_id": "ha-config", "status": "passed"}],
            },
        )
        mocker.patch(
            "src.agents.skills.staf_test._fetch_job_log",
            return_value="PLAY RECAP\nok=5",
        )

        # Mock the POST to submit job
        mock_post_response = mocker.MagicMock()
        mock_post_response.json.return_value = {"id": "job-123"}
        mock_post_response.raise_for_status = mocker.MagicMock()

        mock_async_client = mocker.AsyncMock()
        mock_async_client.post.return_value = mock_post_response
        mock_async_client.__aenter__ = mocker.AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = mocker.AsyncMock(return_value=False)

        mocker.patch(
            "src.agents.skills.staf_test.httpx.AsyncClient",
            return_value=mock_async_client,
        )

        result = await script_fn(
            workspace_id="ws-1",
            test_group="ConfigurationChecks",
            test_ids="configuration-checks",
        )
        parsed = json.loads(result)
        assert parsed["status"] == "completed"
        assert parsed["job_id"] == "job-123"
        assert parsed["workspace_id"] == "ws-1"
        assert "duration_ms" in parsed


class TestPollJob:
    """Tests for _poll_job."""

    @pytest.mark.asyncio
    async def test_immediate_completion(self, mocker: Any) -> None:
        mock_response = mocker.MagicMock()
        mock_response.json.return_value = {"status": "completed"}
        mock_response.raise_for_status = mocker.MagicMock()

        mock_client = mocker.AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mocker.AsyncMock(return_value=False)

        mocker.patch(
            "src.agents.skills.staf_test.httpx.AsyncClient",
            return_value=mock_client,
        )
        mocker.patch("src.agents.skills.staf_test.asyncio.sleep")

        steps: list[dict[str, Any]] = []
        result = await _poll_job("http://test:8000", "job-1", steps)
        assert result == "completed"
        assert len(steps) == 1
        assert steps[0]["status"] == "ok"


class TestFetchHelpers:
    """Tests for _fetch_job_details and _fetch_job_log."""

    @pytest.mark.asyncio
    async def test_fetch_details_success(self, mocker: Any) -> None:
        mock_response = mocker.MagicMock()
        mock_response.json.return_value = {"id": "job-1", "status": "done"}
        mock_response.raise_for_status = mocker.MagicMock()

        mock_client = mocker.AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mocker.AsyncMock(return_value=False)

        mocker.patch(
            "src.agents.skills.staf_test.httpx.AsyncClient",
            return_value=mock_client,
        )

        result = await _fetch_job_details("http://test:8000", "job-1")
        assert result["id"] == "job-1"

    @pytest.mark.asyncio
    async def test_fetch_details_failure(self, mocker: Any) -> None:
        mock_client = mocker.AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("down")
        mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mocker.AsyncMock(return_value=False)

        mocker.patch(
            "src.agents.skills.staf_test.httpx.AsyncClient",
            return_value=mock_client,
        )

        result = await _fetch_job_details("http://test:8000", "job-1")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_fetch_log_success(self, mocker: Any) -> None:
        mock_response = mocker.MagicMock()
        mock_response.text = "log output here"
        mock_response.raise_for_status = mocker.MagicMock()

        mock_client = mocker.AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mocker.AsyncMock(return_value=False)

        mocker.patch(
            "src.agents.skills.staf_test.httpx.AsyncClient",
            return_value=mock_client,
        )

        result = await _fetch_job_log("http://test:8000", "job-1")
        assert result == "log output here"

    @pytest.mark.asyncio
    async def test_fetch_log_failure(self, mocker: Any) -> None:
        mock_client = mocker.AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("down")
        mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mocker.AsyncMock(return_value=False)

        mocker.patch(
            "src.agents.skills.staf_test.httpx.AsyncClient",
            return_value=mock_client,
        )

        result = await _fetch_job_log("http://test:8000", "job-1")
        assert result == ""


class TestTerminalStatuses:
    """Validate terminal status set."""

    def test_contains_expected(self) -> None:
        assert "completed" in _TERMINAL_STATUSES
        assert "failed" in _TERMINAL_STATUSES
        assert "cancelled" in _TERMINAL_STATUSES
        assert "running" not in _TERMINAL_STATUSES
