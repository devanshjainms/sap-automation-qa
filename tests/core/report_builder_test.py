# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for ReportBuilder — findings, playbook/reference matching, summary."""

import pytest

from src.core.analyzer.report import (
    ReportBuilder,
    _classify_failure,
    _map_severity,
)
from src.core.models.failure import FailureClass, Severity
from src.core.models.knowledge import Playbook, Reference, Rule, ValidatorSpec
from src.core.models.validators import ValidatorResult, ValidatorType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _result(
    passed: bool,
    rule_id: str = "R-001",
    expected: str = "true",
    actual: str = "false",
) -> ValidatorResult:
    """Create a minimal ValidatorResult."""
    return ValidatorResult(
        passed=passed,
        rule_id=rule_id,
        expected=expected,
        actual=actual,
        validator_type=ValidatorType.EXACT_MATCH,
        message=f"Expected {expected}, got {actual}",
    )


def _rule(
    rule_id: str = "R-001",
    category: str = "ha_cluster",
    severity: str = "HIGH",
    tags: list[str] | None = None,
) -> Rule:
    """Create a minimal Rule."""
    return Rule(
        id=rule_id,
        name=f"Test {rule_id}",
        description=f"Description for {rule_id}",
        category=category,
        severity=severity,
        tags=tags or [],
        validator=ValidatorSpec(
            type="exact_match",
            source="crm_config",
            parameter="stonith-enabled",
            expected="true",
        ),
    )


def _playbook(
    pb_id: str = "PB-001",
    category: str = "ha_failure",
    tags: list[str] | None = None,
) -> Playbook:
    """Create a minimal Playbook."""
    return Playbook(
        id=pb_id,
        name=f"Playbook {pb_id}",
        category=category,
        tags=tags or [],
        fixes=["Fix step 1", "Fix step 2"],
    )


def _reference(
    ref_id: str = "REF-001",
    tags: list[str] | None = None,
) -> Reference:
    """Create a minimal Reference."""
    return Reference(
        id=ref_id,
        title=f"Reference {ref_id}",
        url=f"https://example.com/{ref_id}",
        tags=tags or [],
    )


# ---------------------------------------------------------------------------
# _map_severity
# ---------------------------------------------------------------------------


class TestMapSeverity:
    """Tests for severity string → enum mapping."""

    def test_critical(self) -> None:
        assert _map_severity("CRITICAL") == Severity.CRITICAL

    def test_high(self) -> None:
        assert _map_severity("HIGH") == Severity.HIGH

    def test_medium(self) -> None:
        assert _map_severity("MEDIUM") == Severity.MEDIUM

    def test_low(self) -> None:
        assert _map_severity("LOW") == Severity.LOW

    def test_info(self) -> None:
        assert _map_severity("INFO") == Severity.INFO

    def test_case_insensitive(self) -> None:
        assert _map_severity("critical") == Severity.CRITICAL
        assert _map_severity("High") == Severity.HIGH

    def test_unknown_defaults_to_medium(self) -> None:
        assert _map_severity("BOGUS") == Severity.MEDIUM
        assert _map_severity("") == Severity.MEDIUM


# ---------------------------------------------------------------------------
# _classify_failure
# ---------------------------------------------------------------------------


class TestClassifyFailure:
    """Tests for failure class heuristic classification."""

    def test_fencing_tag(self) -> None:
        rule = _rule(tags=["fencing", "cluster"])
        assert _classify_failure(rule) == FailureClass.FENCING_NOT_TRIGGERED

    def test_stonith_tag(self) -> None:
        rule = _rule(tags=["stonith"])
        assert _classify_failure(rule) == FailureClass.FENCING_NOT_TRIGGERED

    def test_sbd_tag(self) -> None:
        rule = _rule(tags=["sbd"])
        assert _classify_failure(rule) == FailureClass.SBD_FAILURE

    def test_quorum_tag(self) -> None:
        rule = _rule(tags=["quorum"])
        assert _classify_failure(rule) == FailureClass.QUORUM_LOSS

    def test_hsr_tag(self) -> None:
        rule = _rule(tags=["hsr"])
        assert _classify_failure(rule) == FailureClass.HSR_SYNC_FAILURE

    def test_enqueue_tag(self) -> None:
        rule = _rule(tags=["enqueue"])
        assert _classify_failure(rule) == FailureClass.ENQUEUE_REPLICATION_FAILURE

    def test_constraint_tag(self) -> None:
        rule = _rule(tags=["constraint"])
        assert _classify_failure(rule) == FailureClass.CONSTRAINT_BLOCKING

    def test_sapstartsrv_tag(self) -> None:
        rule = _rule(tags=["sapstartsrv"])
        assert _classify_failure(rule) == FailureClass.SAPSTARTSRV_FAILURE

    def test_category_os_config(self) -> None:
        rule = _rule(category="os_config", tags=[])
        assert _classify_failure(rule) == FailureClass.OS_CONFIG_DRIFT

    def test_category_network(self) -> None:
        rule = _rule(category="network", tags=[])
        assert _classify_failure(rule) == FailureClass.NETWORK_ISOLATION

    def test_category_storage(self) -> None:
        rule = _rule(category="storage", tags=[])
        assert _classify_failure(rule) == FailureClass.STORAGE_THROTTLING

    def test_category_load_balancer(self) -> None:
        rule = _rule(category="load_balancer", tags=[])
        assert _classify_failure(rule) == FailureClass.LOAD_BALANCER_MISCONFIGURED

    def test_tag_takes_priority_over_category(self) -> None:
        rule = _rule(category="os_config", tags=["sbd"])
        assert _classify_failure(rule) == FailureClass.SBD_FAILURE

    def test_unknown_fallback(self) -> None:
        rule = _rule(category="misc", tags=["unrecognized"])
        assert _classify_failure(rule) == FailureClass.UNKNOWN


# ---------------------------------------------------------------------------
# ReportBuilder.build — all passing
# ---------------------------------------------------------------------------


class TestReportBuilderAllPassing:
    """Tests for report building when all rules pass."""

    def test_no_findings(self) -> None:
        results = [_result(True, "R1"), _result(True, "R2")]
        rules = [_rule("R1"), _rule("R2")]
        report = ReportBuilder().build(
            session_id="s1",
            workspace_id="ws",
            results=results,
            rules=rules,
        )
        assert report.finding_count == 0
        assert report.has_critical is False
        assert "passed" in report.summary.lower()

    def test_empty_results(self) -> None:
        report = ReportBuilder().build(
            session_id="s1",
            workspace_id="ws",
            results=[],
            rules=[],
        )
        assert report.finding_count == 0
        assert report.rules_evaluated == 0


# ---------------------------------------------------------------------------
# ReportBuilder.build — failures
# ---------------------------------------------------------------------------


class TestReportBuilderFailures:
    """Tests for report building with failed rules."""

    def test_single_failure(self) -> None:
        results = [_result(False, "R1")]
        rules = [_rule("R1", severity="CRITICAL", category="ha_cluster")]
        report = ReportBuilder().build(
            session_id="s1",
            workspace_id="ws",
            results=results,
            rules=rules,
        )
        assert report.finding_count == 1
        assert report.has_critical is True
        finding = report.findings[0]
        assert finding.rule_id == "R1"
        assert finding.severity == Severity.CRITICAL

    def test_multiple_failures(self) -> None:
        results = [
            _result(False, "R1"),
            _result(True, "R2"),
            _result(False, "R3"),
        ]
        rules = [_rule("R1"), _rule("R2"), _rule("R3")]
        report = ReportBuilder().build(
            session_id="s1",
            workspace_id="ws",
            results=results,
            rules=rules,
        )
        assert report.finding_count == 2
        assert {f.rule_id for f in report.findings} == {"R1", "R3"}

    def test_summary_contains_count(self) -> None:
        results = [_result(False, "R1"), _result(False, "R2")]
        rules = [_rule("R1"), _rule("R2")]
        report = ReportBuilder().build(
            session_id="s1",
            workspace_id="ws",
            results=results,
            rules=rules,
        )
        assert "2 issue(s)" in report.summary

    def test_session_and_workspace_ids(self) -> None:
        report = ReportBuilder().build(
            session_id="s42",
            workspace_id="ws99",
            results=[],
            rules=[],
        )
        assert report.session_id == "s42"
        assert report.workspace_id == "ws99"

    def test_evidence_count_propagated(self) -> None:
        report = ReportBuilder().build(
            session_id="s1",
            workspace_id="ws",
            results=[],
            rules=[],
            evidence_count=7,
        )
        assert report.evidence_count == 7

    def test_duration_propagated(self) -> None:
        report = ReportBuilder().build(
            session_id="s1",
            workspace_id="ws",
            results=[],
            rules=[],
            duration_seconds=1.234,
        )
        assert report.duration_seconds == 1.234

    def test_finding_without_rule_in_map(self) -> None:
        """Result with a rule_id not in the rules list: uses defaults."""
        results = [_result(False, "R-ORPHAN")]
        rules = []  # rule not provided
        report = ReportBuilder().build(
            session_id="s1",
            workspace_id="ws",
            results=results,
            rules=rules,
        )
        assert report.finding_count == 1
        finding = report.findings[0]
        assert finding.severity == Severity.MEDIUM
        assert finding.failure_class == FailureClass.UNKNOWN


# ---------------------------------------------------------------------------
# Playbook matching
# ---------------------------------------------------------------------------


class TestPlaybookMatching:
    """Tests for playbook matching via tags and category."""

    def test_tag_match(self) -> None:
        pb = _playbook(tags=["fencing"])
        rule = _rule(tags=["fencing", "ha"])
        builder = ReportBuilder(playbooks=[pb])
        results = [_result(False, rule.id)]
        report = builder.build(
            session_id="s",
            workspace_id="ws",
            results=results,
            rules=[rule],
        )
        assert report.findings[0].playbook_id == "PB-001"
        assert report.findings[0].remediation == ["Fix step 1", "Fix step 2"]

    def test_category_match(self) -> None:
        pb = _playbook(category="ha_cluster")
        rule = _rule(category="ha_cluster", tags=[])
        builder = ReportBuilder(playbooks=[pb])
        results = [_result(False, rule.id)]
        report = builder.build(
            session_id="s",
            workspace_id="ws",
            results=results,
            rules=[rule],
        )
        assert report.findings[0].playbook_id == pb.id

    def test_no_match(self) -> None:
        pb = _playbook(tags=["network"])
        rule = _rule(tags=["fencing"])
        builder = ReportBuilder(playbooks=[pb])
        results = [_result(False, rule.id)]
        report = builder.build(
            session_id="s",
            workspace_id="ws",
            results=results,
            rules=[rule],
        )
        assert report.findings[0].playbook_id is None
        assert report.findings[0].remediation == []


# ---------------------------------------------------------------------------
# Reference matching
# ---------------------------------------------------------------------------


class TestReferenceMatching:
    """Tests for reference matching via tags."""

    def test_tag_match(self) -> None:
        ref = _reference(tags=["fencing"])
        rule = _rule(tags=["fencing"])
        builder = ReportBuilder(references=[ref])
        results = [_result(False, rule.id)]
        report = builder.build(
            session_id="s",
            workspace_id="ws",
            results=results,
            rules=[rule],
        )
        assert "https://example.com/REF-001" in report.findings[0].references

    def test_no_match(self) -> None:
        ref = _reference(tags=["network"])
        rule = _rule(tags=["fencing"])
        builder = ReportBuilder(references=[ref])
        results = [_result(False, rule.id)]
        report = builder.build(
            session_id="s",
            workspace_id="ws",
            results=results,
            rules=[rule],
        )
        # Rule's own references may be there, but the ref URL won't be
        assert "https://example.com/REF-001" not in report.findings[0].references


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


class TestSummary:
    """Tests for summary generation."""

    def test_all_pass_summary(self) -> None:
        report = ReportBuilder().build(
            session_id="s",
            workspace_id="ws",
            results=[_result(True)],
            rules=[_rule()],
        )
        assert "passed" in report.summary.lower()

    def test_failures_summary_severity_breakdown(self) -> None:
        results = [_result(False, "R1"), _result(False, "R2")]
        rules = [
            _rule("R1", severity="CRITICAL"),
            _rule("R2", severity="HIGH"),
        ]
        report = ReportBuilder().build(
            session_id="s",
            workspace_id="ws",
            results=results,
            rules=rules,
        )
        assert "2 issue(s)" in report.summary
        assert "CRITICAL" in report.summary
        assert "HIGH" in report.summary
