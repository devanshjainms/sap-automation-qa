# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for MCP prompt templates (prompts.py).

Prompts return ``list[base.Message]``. We verify structure, required
content, and parameter interpolation.
"""

from __future__ import annotations

import pytest

from mcp.server.fastmcp.prompts import base

# ---------------------------------------------------------------------------
# triage_sap_cluster
# ---------------------------------------------------------------------------


class TestTriageSapCluster:
    """Test the triage_sap_cluster prompt."""

    def test_returns_single_user_message(self):
        from src.mcp_server.prompts import triage_sap_cluster

        msgs = triage_sap_cluster(workspace_id="WS_A")
        assert len(msgs) == 1
        assert isinstance(msgs[0], base.UserMessage)

    def test_contains_workspace_id(self):
        from src.mcp_server.prompts import triage_sap_cluster

        msgs = triage_sap_cluster(workspace_id="MY_WS")
        assert "MY_WS" in msgs[0].content.text

    def test_contains_all_tool_steps(self):
        from src.mcp_server.prompts import triage_sap_cluster

        msgs = triage_sap_cluster(workspace_id="WS_A")
        text = msgs[0].content.text
        assert "collect_evidence" in text
        assert "get_analysis_context" in text

    def test_appends_issue_description(self):
        from src.mcp_server.prompts import triage_sap_cluster

        msgs = triage_sap_cluster(
            workspace_id="WS_A",
            issue_description="cluster split brain",
        )
        text = msgs[0].content.text
        assert "cluster split brain" in text
        assert "Focus your analysis" in text

    def test_no_issue_description_omits_focus(self):
        from src.mcp_server.prompts import triage_sap_cluster

        msgs = triage_sap_cluster(workspace_id="WS_A")
        assert "Focus your analysis" not in msgs[0].content.text


# ---------------------------------------------------------------------------
# run_ha_test_suite
# ---------------------------------------------------------------------------


class TestRunHaTestSuite:
    """Test the run_ha_test_suite prompt."""

    def test_returns_single_user_message(self):
        from src.mcp_server.prompts import run_ha_test_suite

        msgs = run_ha_test_suite(workspace_id="WS_A")
        assert len(msgs) == 1
        assert isinstance(msgs[0], base.UserMessage)

    def test_contains_workspace_and_test_group(self):
        from src.mcp_server.prompts import run_ha_test_suite

        msgs = run_ha_test_suite(
            workspace_id="WS_B",
            test_group="CentralServicesHighAvailability",
        )
        text = msgs[0].content.text
        assert "WS_B" in text
        assert "CentralServicesHighAvailability" in text

    def test_default_test_group(self):
        from src.mcp_server.prompts import run_ha_test_suite

        msgs = run_ha_test_suite(workspace_id="WS_A")
        assert "DatabaseHighAvailability" in msgs[0].content.text

    def test_contains_tool_steps(self):
        from src.mcp_server.prompts import run_ha_test_suite

        msgs = run_ha_test_suite(workspace_id="WS_A")
        text = msgs[0].content.text
        assert "run_staf_test" in text
        assert "get_job_status" in text
        assert "get_job_results" in text


# ---------------------------------------------------------------------------
# investigate_sap_note
# ---------------------------------------------------------------------------


class TestInvestigateSapNote:
    """Test the investigate_sap_note prompt."""

    def test_returns_single_user_message(self):
        from src.mcp_server.prompts import investigate_sap_note

        msgs = investigate_sap_note(keyword="STONITH")
        assert len(msgs) == 1
        assert isinstance(msgs[0], base.UserMessage)

    def test_contains_keyword(self):
        from src.mcp_server.prompts import investigate_sap_note

        msgs = investigate_sap_note(keyword="SAP Note 2369910")
        assert "SAP Note 2369910" in msgs[0].content.text

    def test_contains_knowledge_tool_reference(self):
        from src.mcp_server.prompts import investigate_sap_note

        msgs = investigate_sap_note(keyword="STONITH")
        text = msgs[0].content.text
        assert "query_knowledge" in text
