# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""MCP prompts — reusable templates for SAP triage and testing workflows.

Prompts are pre-built interaction patterns that guide the LLM through
multi-step SAP operations. Clients can invoke these to get structured
instructions rather than free-forming every request.
"""

from __future__ import annotations
from mcp.server.fastmcp.prompts import base
from src.mcp_server.server import mcp


@mcp.prompt(title="SAP Cluster Triage")
def triage_sap_cluster(
    workspace_id: str,
    issue_description: str = "",
) -> list[base.Message]:
    """Full triage workflow for an SAP cluster issue.

    Guides the LLM through: collect evidence → analyze → report.
    """
    steps = (
        f"Triage the SAP cluster in workspace '{workspace_id}'.\n\n"
        "Follow these steps in order:\n"
        "1. Call collect_evidence with the workspace_id to gather "
        "cluster status, CIB XML, and system replication state.\n"
        "2. Once collection completes, call get_analysis_context with the "
        "returned session_id to load evidence and applicable rules.\n"
        "3. Analyze the evidence against the rules. Identify configuration "
        "issues, cluster health problems, and suggest remediation.\n"
    )
    if issue_description:
        steps += (
            f"\nThe user reports this issue: {issue_description}\n"
            "Focus your analysis on findings related to this symptom."
        )
    return [base.UserMessage(steps)]


@mcp.prompt(title="Run HA Test Suite")
def run_ha_test_suite(
    workspace_id: str,
    test_group: str = "DatabaseHighAvailability",
) -> list[base.Message]:
    """Execute and monitor a full HA test suite.

    Guides the LLM through: run test → poll → report results.
    """
    return [
        base.UserMessage(
            f"Execute the '{test_group}' test suite on workspace "
            f"'{workspace_id}'.\n\n"
            "Follow these steps:\n"
            "1. Call run_staf_test with the workspace_id and "
            "test_group.\n"
            "2. Poll get_job_status with the returned job_id every "
            "10 seconds until is_terminal is true.\n"
            "3. Call get_job_results to retrieve the full results.\n"
            "4. Summarize: which tests passed, which failed, and "
            "suggest next steps for any failures."
        )
    ]


@mcp.prompt(title="Investigate SAP Note")
def investigate_sap_note(
    keyword: str,
) -> list[base.Message]:
    """Search the knowledge base for rules related to a keyword or SAP Note.

    Useful when a specific error or SAP Note number needs investigation.
    """
    return [
        base.UserMessage(
            f"Search the knowledge base for '{keyword}'.\n\n"
            "1. Call query_knowledge with the keyword.\n"
            "2. If rules are found, explain what each rule checks "
            "and its severity.\n"
            "3. If playbooks are found, explain the remediation "
            "steps.\n"
            "4. Provide a concise summary of how this keyword "
            "relates to SAP HA best practices."
        )
    ]
