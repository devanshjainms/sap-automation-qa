# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for Analyzer facade — normalization, validation, report, session lifecycle.

Includes the three exit-criteria scenarios from STAF.md Phase 3:
1. HANA HA cluster with fencing disabled
2. OS config with wrong kernel params
3. Clean system with no findings
"""

import pytest

from src.core.analyzer.analyzer import Analyzer
from src.core.analyzer.normalizers import (
    CibXmlNormalizer,
    KeyValueNormalizer,
    NormalizedData,
    NormalizerRegistry,
    SysctlNormalizer,
)
from src.core.analyzer.report import ReportBuilder
from src.core.analyzer.validators import RuleValidator
from src.core.models.evidence import (
    CollectionStatus,
    CollectorType,
    EvidenceArtifact,
    EvidenceType,
)
from src.core.models.failure import FailureClass, Severity
from src.core.models.knowledge import Playbook, Reference, Rule, ValidatorSpec
from src.core.models.triage import TriageSession, TriageStatus
from src.core.models.validators import ValidatorType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _artifact(
    content: str,
    source: str = "",
    evidence_id: str = "evi-test",
    evidence_type: EvidenceType = EvidenceType.COMMAND_OUTPUT,
    command: str = "test-cmd",
    status: CollectionStatus = CollectionStatus.SUCCESS,
) -> EvidenceArtifact:
    """Create a minimal evidence artifact."""
    return EvidenceArtifact(
        evidence_id=evidence_id,
        evidence_type=evidence_type,
        collector_type=CollectorType.SSH,
        status=status,
        host="node01",
        command=command,
        content=content,
        metadata={"source": source} if source else {},
    )


def _rule(
    rule_id: str = "R-001",
    source: str = "crm_config",
    parameter: str = "stonith-enabled",
    expected: str = "true",
    vtype: ValidatorType = ValidatorType.EXACT_MATCH,
    severity: str = "CRITICAL",
    category: str = "ha_cluster",
    tags: list[str] | None = None,
    **kwargs,
) -> Rule:
    return Rule(
        id=rule_id,
        name=f"Test {rule_id}",
        description=f"Check {parameter}",
        category=category,
        severity=severity,
        tags=tags or [],
        validator=ValidatorSpec(
            type=vtype,
            source=source,
            parameter=parameter,
            expected=expected,
            **kwargs,
        ),
    )


def _session(status: TriageStatus = TriageStatus.ANALYZING) -> TriageSession:
    """Create a TriageSession in ANALYZING state ready for analysis."""
    session = TriageSession(workspace_id="ws-test")
    # Walk the state machine to ANALYZING
    session.start_collection()
    session.complete_collection([])
    return session


# ---------------------------------------------------------------------------
# CIB XML fixture
# ---------------------------------------------------------------------------

CIB_FENCING_DISABLED = """\
<cib>
  <configuration>
    <crm_config>
      <cluster_property_set id="cib-bootstrap-options">
        <nvpair id="stonith-enabled" name="stonith-enabled" value="false"/>
        <nvpair id="stonith-timeout" name="stonith-timeout" value="150"/>
      </cluster_property_set>
    </crm_config>
    <rsc_defaults>
      <meta_attributes id="rsc-options">
        <nvpair id="resource-stickiness" name="resource-stickiness" value="1000"/>
      </meta_attributes>
    </rsc_defaults>
  </configuration>
</cib>"""

CIB_FENCING_ENABLED = """\
<cib>
  <configuration>
    <crm_config>
      <cluster_property_set id="cib-bootstrap-options">
        <nvpair id="stonith-enabled" name="stonith-enabled" value="true"/>
      </cluster_property_set>
    </crm_config>
  </configuration>
</cib>"""


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestAnalyzerConstruction:
    """Tests for Analyzer initialization and defaults."""

    def test_defaults(self) -> None:
        analyzer = Analyzer()
        assert isinstance(analyzer.normalizer_registry, NormalizerRegistry)
        assert isinstance(analyzer.rule_validator, RuleValidator)
        assert isinstance(analyzer.report_builder, ReportBuilder)

    def test_custom_injection(self) -> None:
        reg = NormalizerRegistry()
        val = RuleValidator()
        report = ReportBuilder()
        analyzer = Analyzer(reg, val, report)
        assert analyzer.normalizer_registry is reg
        assert analyzer.rule_validator is val
        assert analyzer.report_builder is report


# ---------------------------------------------------------------------------
# _filter_usable
# ---------------------------------------------------------------------------


class TestFilterUsable:
    """Tests for usable artifact filtering."""

    def test_only_success_kept(self) -> None:
        good = _artifact("ok", source="sysctl")
        bad = _artifact("err", source="sysctl", status=CollectionStatus.FAILED)
        result = Analyzer()._filter_usable([good, bad])
        assert len(result) == 1
        assert result[0] is good

    def test_all_usable(self) -> None:
        arts = [_artifact("a"), _artifact("b")]
        assert len(Analyzer()._filter_usable(arts)) == 2

    def test_empty_list(self) -> None:
        assert Analyzer()._filter_usable([]) == []


# ---------------------------------------------------------------------------
# _infer_source
# ---------------------------------------------------------------------------


class TestInferSource:
    """Tests for source inference from artifact evidence type."""

    def test_cib_xml_type(self) -> None:
        art = _artifact("xml", evidence_type=EvidenceType.CIB_XML)
        assert Analyzer()._infer_source(art) == "cib_resource"

    def test_log_type(self) -> None:
        art = _artifact("lines", evidence_type=EvidenceType.LOG_EXCERPT)
        assert Analyzer()._infer_source(art) == "log"

    def test_command_output_defaults_to_command(self) -> None:
        """Source comes from metadata, not command strings."""
        art = _artifact("data", command="sysctl -a")
        assert Analyzer()._infer_source(art) == "command"

    def test_unknown_defaults_to_command(self) -> None:
        art = _artifact("data", command="unknown-tool")
        assert Analyzer()._infer_source(art) == "command"


# ---------------------------------------------------------------------------
# _normalize_all
# ---------------------------------------------------------------------------


class TestNormalizeAll:
    """Tests for normalizing artifact collections."""

    def test_single_artifact(self) -> None:
        art = _artifact("k = v\n", source="sysctl")
        data_map = Analyzer()._normalize_all([art])
        assert "sysctl" in data_map
        assert data_map["sysctl"].get("k") == "v"

    def test_no_source_uses_evidence_type(self) -> None:
        """Without metadata source, inference uses evidence type."""
        art = _artifact("k = v\n", command="sysctl -a")
        data_map = Analyzer()._normalize_all([art])
        # No source metadata, COMMAND_OUTPUT type → inferred as "command"
        assert "command" in data_map

    def test_unknown_normalizer_skipped(self) -> None:
        reg = NormalizerRegistry()  # empty registry
        analyzer = Analyzer(normalizer_registry=reg)
        art = _artifact("data", source="xyz")
        data_map = analyzer._normalize_all([art])
        assert len(data_map) == 0

    def test_multiple_artifacts_same_source_merged(self) -> None:
        art1 = _artifact("a = 1\n", source="sysctl")
        art2 = _artifact("b = 2\n", source="sysctl")
        data_map = Analyzer()._normalize_all([art1, art2])
        assert data_map["sysctl"].get("a") == "1"
        assert data_map["sysctl"].get("b") == "2"

    def test_cib_fan_out_to_peer_sources(self) -> None:
        """One CIB artifact populates all CIB peer sources."""
        art = _artifact(
            CIB_FENCING_ENABLED,
            source="crm_config",
            evidence_type=EvidenceType.CIB_XML,
        )
        data_map = Analyzer()._normalize_all([art])
        # crm_config is the primary source
        assert "crm_config" in data_map
        assert data_map["crm_config"].get("stonith-enabled") == "true"
        # Peer sources also populated via fan-out
        for peer in ("op_defaults", "rsc_defaults", "constraints", "cib_resource"):
            assert peer in data_map, f"Missing peer source: {peer}"


# ---------------------------------------------------------------------------
# _filter_rules_with_evidence
# ---------------------------------------------------------------------------


class TestFilterRulesWithEvidence:
    """Tests for filtering rules by available evidence."""

    def test_keeps_rules_with_evidence(self) -> None:
        rules = [_rule(source="sysctl", parameter="vm.swappiness")]
        data_map = {"sysctl": NormalizedData(source="sysctl", values={"vm.swappiness": "10"})}
        result = Analyzer()._filter_rules_with_evidence(rules, data_map)
        assert len(result) == 1

    def test_skips_rules_without_evidence(self) -> None:
        rules = [_rule(source="sysctl")]
        result = Analyzer()._filter_rules_with_evidence(rules, {})
        assert len(result) == 0

    def test_skips_rules_when_parameter_missing(self) -> None:
        """Rule source exists but the specific parameter is not in the data."""
        rules = [_rule(source="command", parameter="stonith-enabled")]
        data_map = {
            "command": NormalizedData(source="command", values={"hdbnameserver": "running"})
        }
        result = Analyzer()._filter_rules_with_evidence(rules, data_map)
        assert len(result) == 0

    def test_rules_without_source_kept(self) -> None:
        """Rules with empty source are always included."""
        rule = Rule(id="R-X", name="General", validator=None)
        result = Analyzer()._filter_rules_with_evidence([rule], {})
        assert len(result) == 1

    def test_mixed(self) -> None:
        rules = [
            _rule(rule_id="R1", source="sysctl", parameter="vm.swappiness"),
            _rule(rule_id="R2", source="missing"),
        ]
        data_map = {"sysctl": NormalizedData(source="sysctl", values={"vm.swappiness": "10"})}
        result = Analyzer()._filter_rules_with_evidence(rules, data_map)
        assert len(result) == 1
        assert result[0].id == "R1"


# ---------------------------------------------------------------------------
# analyze_artifacts (stateless)
# ---------------------------------------------------------------------------


class TestAnalyzeArtifacts:
    """Tests for analyze_artifacts — no session state management."""

    def test_basic(self) -> None:
        art = _artifact("vm.swappiness = 10\n", source="sysctl")
        rule = _rule(source="sysctl", parameter="vm.swappiness", expected="10")
        results, data_map = Analyzer().analyze_artifacts([art], [rule])
        assert len(results) == 1
        assert results[0].passed is True
        assert "sysctl" in data_map

    def test_failed_artifact_excluded(self) -> None:
        art = _artifact("content", source="sysctl", status=CollectionStatus.FAILED)
        rule = _rule(source="sysctl", parameter="x", expected="y")
        results, data_map = Analyzer().analyze_artifacts([art], [rule])
        assert "sysctl" not in data_map

    def test_empty(self) -> None:
        results, data_map = Analyzer().analyze_artifacts([], [])
        assert results == []
        assert data_map == {}


# ---------------------------------------------------------------------------
# EXIT CRITERIA SCENARIO 1: HANA HA — fencing disabled
# ---------------------------------------------------------------------------


class TestScenarioHanaFencingDisabled:
    """Scenario: HANA HA cluster with stonith-enabled=false."""

    def test_detects_fencing_disabled(self) -> None:
        art = _artifact(
            CIB_FENCING_DISABLED,
            source="crm_config",
            evidence_type=EvidenceType.CIB_XML,
            command="cibadmin --query",
        )
        rule = _rule(
            rule_id="DB-HANA-0001",
            source="crm_config",
            parameter="stonith-enabled",
            expected="true",
            severity="CRITICAL",
            category="ha_cluster",
            tags=["fencing", "stonith"],
        )
        session = _session()
        report = Analyzer().analyze(session, [art], [rule])

        assert report.finding_count == 1
        finding = report.findings[0]
        assert finding.severity == Severity.CRITICAL
        assert finding.failure_class == FailureClass.FENCING_NOT_TRIGGERED
        assert finding.rule_id == "DB-HANA-0001"
        assert session.status == TriageStatus.COMPLETE.value

    def test_fencing_enabled_passes(self) -> None:
        art = _artifact(
            CIB_FENCING_ENABLED,
            source="crm_config",
            evidence_type=EvidenceType.CIB_XML,
            command="cibadmin --query",
        )
        rule = _rule(
            rule_id="DB-HANA-0001",
            source="crm_config",
            parameter="stonith-enabled",
            expected="true",
            tags=["fencing"],
        )
        session = _session()
        report = Analyzer().analyze(session, [art], [rule])
        assert report.finding_count == 0


# ---------------------------------------------------------------------------
# EXIT CRITERIA SCENARIO 2: OS config — wrong kernel params
# ---------------------------------------------------------------------------


class TestScenarioWrongKernelParams:
    """Scenario: OS configuration with incorrect sysctl values."""

    def test_detects_wrong_swappiness(self) -> None:
        art = _artifact(
            "vm.swappiness = 60\nnet.ipv4.tcp_keepalive_time = 300\n",
            source="sysctl",
        )
        rules = [
            _rule(
                rule_id="OS-001",
                source="sysctl",
                parameter="vm.swappiness",
                expected="10",
                severity="HIGH",
                category="os_config",
            ),
            _rule(
                rule_id="OS-002",
                source="sysctl",
                parameter="net.ipv4.tcp_keepalive_time",
                expected="300",
                severity="MEDIUM",
                category="os_config",
            ),
        ]
        session = _session()
        report = Analyzer().analyze(session, [art], rules)

        assert report.finding_count == 1
        finding = report.findings[0]
        assert finding.rule_id == "OS-001"
        assert finding.severity == Severity.HIGH
        assert finding.failure_class == FailureClass.OS_CONFIG_DRIFT

    def test_all_kernel_params_correct(self) -> None:
        art = _artifact(
            "vm.swappiness = 10\nnet.ipv4.tcp_keepalive_time = 300\n",
            source="sysctl",
        )
        rules = [
            _rule(
                rule_id="OS-001",
                source="sysctl",
                parameter="vm.swappiness",
                expected="10",
                category="os_config",
            ),
            _rule(
                rule_id="OS-002",
                source="sysctl",
                parameter="net.ipv4.tcp_keepalive_time",
                expected="300",
                category="os_config",
            ),
        ]
        session = _session()
        report = Analyzer().analyze(session, [art], rules)
        assert report.finding_count == 0


# ---------------------------------------------------------------------------
# EXIT CRITERIA SCENARIO 3: Clean system — no findings
# ---------------------------------------------------------------------------


class TestScenarioCleanSystem:
    """Scenario: All rules pass, no findings generated."""

    def test_clean_system(self) -> None:
        cib_art = _artifact(
            CIB_FENCING_ENABLED,
            source="crm_config",
            evidence_type=EvidenceType.CIB_XML,
        )
        sysctl_art = _artifact(
            "vm.swappiness = 10\n",
            source="sysctl",
        )
        rules = [
            _rule(
                rule_id="R1",
                source="crm_config",
                parameter="stonith-enabled",
                expected="true",
            ),
            _rule(
                rule_id="R2",
                source="sysctl",
                parameter="vm.swappiness",
                expected="10",
            ),
        ]
        session = _session()
        report = Analyzer().analyze(session, [cib_art, sysctl_art], rules)

        assert report.finding_count == 0
        assert report.has_critical is False
        assert "passed" in report.summary.lower()
        assert session.status == TriageStatus.COMPLETE.value
        assert session.report is not None


# ---------------------------------------------------------------------------
# Session state management
# ---------------------------------------------------------------------------


class TestSessionStateManagement:
    """Tests for session state transitions during analysis."""

    def test_advances_to_complete(self) -> None:
        session = _session()
        assert session.status == TriageStatus.ANALYZING.value
        Analyzer().analyze(session, [], [])
        assert session.status == TriageStatus.COMPLETE.value

    def test_report_attached_to_session(self) -> None:
        session = _session()
        report = Analyzer().analyze(session, [], [])
        assert session.report is report

    def test_report_has_session_id(self) -> None:
        session = _session()
        report = Analyzer().analyze(session, [], [])
        assert report.session_id == str(session.id)

    def test_report_has_workspace_id(self) -> None:
        session = _session()
        report = Analyzer().analyze(session, [], [])
        assert report.workspace_id == "ws-test"


# ---------------------------------------------------------------------------
# Playbook/reference integration
# ---------------------------------------------------------------------------


class TestPlaybookReferenceIntegration:
    """Tests for playbook/reference matching through the full facade."""

    def test_playbook_matched(self) -> None:
        pb = Playbook(
            id="PB-1",
            name="Fencing fix",
            category="ha_failure",
            tags=["fencing"],
            fixes=["Enable stonith"],
        )
        report_builder = ReportBuilder(playbooks=[pb])
        analyzer = Analyzer(report_builder=report_builder)

        art = _artifact(
            CIB_FENCING_DISABLED, source="crm_config", evidence_type=EvidenceType.CIB_XML
        )
        rule = _rule(
            source="crm_config",
            parameter="stonith-enabled",
            expected="true",
            tags=["fencing"],
        )
        session = _session()
        report = analyzer.analyze(session, [art], [rule])
        assert report.findings[0].playbook_id == "PB-1"
        assert "Enable stonith" in report.findings[0].remediation

    def test_reference_matched(self) -> None:
        ref = Reference(
            id="REF-1",
            title="SAP Note 123",
            url="https://example.com/123",
            tags=["fencing"],
        )
        report_builder = ReportBuilder(references=[ref])
        analyzer = Analyzer(report_builder=report_builder)

        art = _artifact(
            CIB_FENCING_DISABLED, source="crm_config", evidence_type=EvidenceType.CIB_XML
        )
        rule = _rule(
            source="crm_config",
            parameter="stonith-enabled",
            expected="true",
            tags=["fencing"],
        )
        session = _session()
        report = analyzer.analyze(session, [art], [rule])
        assert "https://example.com/123" in report.findings[0].references


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Miscellaneous edge cases."""

    def test_no_usable_artifacts(self) -> None:
        art = _artifact("data", source="sysctl", status=CollectionStatus.FAILED)
        rule = _rule(source="sysctl")
        session = _session()
        report = Analyzer().analyze(session, [art], [rule])
        assert report.finding_count == 0

    def test_rules_without_matching_evidence_skipped(self) -> None:
        rule = _rule(source="nonexistent")
        session = _session()
        report = Analyzer().analyze(session, [], [rule])
        assert report.finding_count == 0
        assert report.rules_evaluated == 0

    def test_empty_artifacts_and_rules(self) -> None:
        session = _session()
        report = Analyzer().analyze(session, [], [])
        assert report.finding_count == 0
        assert session.status == TriageStatus.COMPLETE.value

    def test_report_duration_is_positive(self) -> None:
        session = _session()
        report = Analyzer().analyze(session, [], [])
        assert report.duration_seconds is not None
        assert report.duration_seconds >= 0
