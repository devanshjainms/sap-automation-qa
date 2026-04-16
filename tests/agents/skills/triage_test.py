# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the SAP triage skill."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.agents.skills.triage import (
    _build_evidence_definitions,
    _build_summary,
    _resolve_placeholders,
    build_triage_skill,
)


@dataclass
class _FakeWorkspace:
    id: str = "DEV-WEEU-SAP01-X00"
    name: str = "DEV"
    environment: str = "dev"


@dataclass
class _FakeDef:
    id: str = "hana-sr-state"
    description: str = "HANA SR state"
    command: str = "su - <sid>adm -c 'HDBSettings.sh landscapeHostConfiguration.py'"
    tags: list[str] = field(default_factory=lambda: ["hana", "sr"])
    evidence_type: str = "command_output"
    source: str = "sap-best-practice"
    ok_exit_codes: list[int] = field(default_factory=lambda: [0])
    max_timeout_seconds: int = 30
    requires_ha: bool = False


@dataclass
class _FakeSshCred:
    private_key_path: str = "/tmp/ssh_key"

    @dataclass
    class _AuthType:
        value: str = "ssh_key"

    auth_type: _AuthType = field(default_factory=_AuthType)


@dataclass
class _FakeFinding:
    finding_id: str = "F-001"
    title: str = "HSR not configured"
    severity: str = "critical"
    failure_class: str = "config"
    description: str = "System replication is not running."
    remediation: str = "Run sr_register."
    rule_id: str = "R-001"
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class _FakeReport:
    finding_count: int = 1
    rules_evaluated: int = 10
    rules_passed: int = 9
    evidence_count: int = 5
    has_critical: bool = True
    findings: list[_FakeFinding] = field(default_factory=lambda: [_FakeFinding()])
    summary: str = ""


def _make_sap_context(mocker: Any) -> MagicMock:
    """Build a mock SapContext with all required attributes."""
    ctx = MagicMock()
    ctx.workspaces_base = "/tmp/WORKSPACES/SYSTEM"
    ctx.knowledge_store.load_evidence_definitions.return_value = [_FakeDef()]
    ctx.knowledge_store.load_rules.return_value = []
    ctx.ssh_cache.provision.return_value = _FakeSshCred()
    ctx.triage_executor.collect.return_value = []
    ctx.analyzer.analyze.return_value = _FakeReport()
    ctx.retriever.search_evidence_definitions.return_value = []
    return ctx


class TestResolvePlaceholders:
    """Tests for _resolve_placeholders."""

    def test_replaces_sid_and_nr(self) -> None:
        cmd = "su - <sid>adm -c 'hdbsql -i <NR>'"
        result = _resolve_placeholders(
            cmd,
            {
                "db_sid": "HN1",
                "db_instance_number": "03",
            },
        )
        assert result == "su - hn1adm -c 'hdbsql -i 03'"

    def test_replaces_upper_sid(self) -> None:
        cmd = "sapcontrol -nr <NR> -function GetProcessList -host <SID>"
        result = _resolve_placeholders(
            cmd,
            {
                "sap_sid": "DEV",
                "scs_instance_number": "00",
            },
        )
        assert result == "sapcontrol -nr 00 -function GetProcessList -host DEV"

    def test_no_placeholders(self) -> None:
        cmd = "df -h"
        assert _resolve_placeholders(cmd, {}) == "df -h"

    def test_empty_vars(self) -> None:
        cmd = "su - <sid>adm"
        result = _resolve_placeholders(cmd, {})
        # No db_sid or sap_sid → <sid> remains unresolved
        assert result == "su - <sid>adm"


class TestBuildEvidenceDefinitions:
    """Tests for _build_evidence_definitions."""

    def test_creates_cross_product(self) -> None:
        hosts = ["10.0.0.1", "10.0.0.2"]
        host_details = [
            {"ansible_host": "10.0.0.1", "ansible_user": "root"},
            {"ansible_host": "10.0.0.2", "ansible_user": "root"},
        ]
        defs = _build_evidence_definitions(
            collector_defs=[_FakeDef()],
            hosts=hosts,
            host_details=host_details,
            extra_vars={"db_sid": "HN1"},
            ssh_credential=_FakeSshCred(),
            workspace_id="ws-1",
        )
        assert len(defs) == 2
        assert defs[0].definition_id == "hana-sr-state@10.0.0.1"
        assert defs[1].definition_id == "hana-sr-state@10.0.0.2"

    def test_resolves_command_placeholders(self) -> None:
        defs = _build_evidence_definitions(
            collector_defs=[_FakeDef()],
            hosts=["10.0.0.1"],
            host_details=[{"ansible_host": "10.0.0.1"}],
            extra_vars={"db_sid": "HN1"},
            ssh_credential=_FakeSshCred(),
            workspace_id="ws-1",
        )
        assert "<sid>" not in defs[0].command
        assert "hn1" in defs[0].command


class TestBuildSummary:
    """Tests for _build_summary."""

    def test_no_findings(self) -> None:
        report = _FakeReport(finding_count=0, findings=[], has_critical=False)
        summary = _build_summary(report)
        assert "No issues" in summary

    def test_with_critical(self) -> None:
        report = _FakeReport()
        summary = _build_summary(report)
        assert "1 finding" in summary
        assert "critical" in summary


class TestBuildTriageSkill:
    """Tests for build_triage_skill factory."""

    def test_skill_metadata(self) -> None:
        ctx = MagicMock()
        ctx.workspaces_base = "/tmp"
        ctx.knowledge_store.load_evidence_definitions.return_value = []
        skill = build_triage_skill(ctx)
        assert skill.name == "sap-triage"
        assert skill.description
        assert skill.content
        assert len(skill.resources) == 2
        assert len(skill.scripts) == 1

    def test_workspaces_resource(self, mocker: Any) -> None:
        ctx = MagicMock()
        ctx.workspaces_base = "/tmp"
        mocker.patch(
            "src.agents.skills.triage.load_workspaces_from_directory",
            return_value=[_FakeWorkspace()],
        )
        skill = build_triage_skill(ctx)
        ws_resource = skill.resources[0]
        result = ws_resource.function()
        assert "DEV-WEEU-SAP01-X00" in result

    def test_evidence_catalog_resource(self) -> None:
        ctx = MagicMock()
        ctx.workspaces_base = "/tmp"
        ctx.knowledge_store.load_evidence_definitions.return_value = [_FakeDef()]
        skill = build_triage_skill(ctx)
        catalog_resource = skill.resources[1]
        result = catalog_resource.function()
        assert "hana-sr-state" in result

    def test_evidence_catalog_empty(self) -> None:
        ctx = MagicMock()
        ctx.workspaces_base = "/tmp"
        ctx.knowledge_store.load_evidence_definitions.return_value = []
        skill = build_triage_skill(ctx)
        catalog_resource = skill.resources[1]
        result = catalog_resource.function()
        assert "No evidence" in result


class TestInvestigateScript:
    """Tests for the investigate script execution."""

    @pytest.mark.asyncio
    async def test_investigate_no_hosts(self, mocker: Any) -> None:
        ctx = _make_sap_context(mocker)
        mocker.patch(
            "src.agents.skills.triage.load_workspace_host_details",
            return_value=[],
        )
        skill = build_triage_skill(ctx)
        script_fn = skill.scripts[0].function
        result = await script_fn(workspace_id="ws-1", query="test")
        parsed = json.loads(result)
        assert parsed["status"] == "failed"
        assert "No hosts" in parsed["error"]

    @pytest.mark.asyncio
    async def test_investigate_no_ssh(self, mocker: Any) -> None:
        ctx = _make_sap_context(mocker)
        ctx.ssh_cache.provision.return_value = None
        mocker.patch(
            "src.agents.skills.triage.load_workspace_host_details",
            return_value=[{"ansible_host": "10.0.0.1"}],
        )
        mocker.patch(
            "src.agents.skills.triage.load_workspace_params",
            return_value={},
        )
        skill = build_triage_skill(ctx)
        script_fn = skill.scripts[0].function
        result = await script_fn(workspace_id="ws-1")
        parsed = json.loads(result)
        assert parsed["status"] == "failed"
        assert "SSH" in parsed["error"]

    @pytest.mark.asyncio
    async def test_investigate_success(self, mocker: Any) -> None:
        ctx = _make_sap_context(mocker)
        mocker.patch(
            "src.agents.skills.triage.load_workspace_host_details",
            return_value=[{"ansible_host": "10.0.0.1"}],
        )
        mocker.patch(
            "src.agents.skills.triage.load_workspace_params",
            return_value={"db_sid": "HN1", "database_high_availability": True},
        )
        skill = build_triage_skill(ctx)
        script_fn = skill.scripts[0].function
        result = await script_fn(workspace_id="ws-1", query="health check")
        parsed = json.loads(result)
        assert parsed["status"] == "completed"
        assert "findings" in parsed
        assert parsed["finding_count"] == 1

    @pytest.mark.asyncio
    async def test_investigate_exception(self, mocker: Any) -> None:
        ctx = _make_sap_context(mocker)
        mocker.patch(
            "src.agents.skills.triage.load_workspace_host_details",
            side_effect=RuntimeError("Connection refused"),
        )
        skill = build_triage_skill(ctx)
        script_fn = skill.scripts[0].function
        result = await script_fn(workspace_id="ws-1")
        parsed = json.loads(result)
        assert parsed["status"] == "failed"
        assert "Connection refused" in parsed["error"]
