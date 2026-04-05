# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Report builder — assembles findings, playbooks, and references into a TriageReport."""

import logging
from typing import Optional
from uuid import uuid4

from src.core.models.failure import FailureClass, Severity
from src.core.models.knowledge import Playbook, Reference, Rule
from src.core.models.triage import TriageFinding, TriageReport
from src.core.models.validators import ValidatorResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Severity mapping from rule severity strings to Severity enum
# ---------------------------------------------------------------------------

_SEVERITY_MAP: dict[str, Severity] = {
    "CRITICAL": Severity.CRITICAL,
    "HIGH": Severity.HIGH,
    "MEDIUM": Severity.MEDIUM,
    "LOW": Severity.LOW,
    "INFO": Severity.INFO,
}


def _map_severity(severity_str: str) -> Severity:
    """Convert a rule severity string to a Severity enum.

    :param severity_str: Severity string from the rule.
    :returns: Corresponding Severity enum value.
    """
    return _SEVERITY_MAP.get(severity_str.upper(), Severity.MEDIUM)


# ---------------------------------------------------------------------------
# Failure class heuristics
# ---------------------------------------------------------------------------

_CATEGORY_TO_FAILURE: dict[str, FailureClass] = {
    "ha_cluster": FailureClass.FENCING_NOT_TRIGGERED,
    "os_config": FailureClass.OS_CONFIG_DRIFT,
    "network": FailureClass.NETWORK_ISOLATION,
    "storage": FailureClass.STORAGE_THROTTLING,
    "load_balancer": FailureClass.LOAD_BALANCER_MISCONFIGURED,
}

_TAG_TO_FAILURE: dict[str, FailureClass] = {
    "fencing": FailureClass.FENCING_NOT_TRIGGERED,
    "stonith": FailureClass.FENCING_NOT_TRIGGERED,
    "sbd": FailureClass.SBD_FAILURE,
    "quorum": FailureClass.QUORUM_LOSS,
    "hsr": FailureClass.HSR_SYNC_FAILURE,
    "enqueue": FailureClass.ENQUEUE_REPLICATION_FAILURE,
    "sapstartsrv": FailureClass.SAPSTARTSRV_FAILURE,
    "constraint": FailureClass.CONSTRAINT_BLOCKING,
}


def _classify_failure(rule: Rule) -> FailureClass:
    """Heuristically classify a rule failure based on category and tags.

    :param rule: The rule that failed validation.
    :returns: Best-guess failure classification.
    """
    for tag in rule.tags:
        tag_lower = tag.lower()
        for keyword, fc in _TAG_TO_FAILURE.items():
            if keyword in tag_lower:
                return fc

    category_lower = rule.category.lower()
    for keyword, fc in _CATEGORY_TO_FAILURE.items():
        if keyword in category_lower:
            return fc

    return FailureClass.UNKNOWN


# ---------------------------------------------------------------------------
# ReportBuilder
# ---------------------------------------------------------------------------


class ReportBuilder:
    """Assembles validation results into a structured TriageReport.

    Takes failed ``ValidatorResult`` objects, matches them to playbooks
    and references, and produces ``TriageFinding`` objects.

    :param playbooks: Available playbooks for remediation matching.
    :param references: Available references for linking.
    """

    def __init__(
        self,
        playbooks: Optional[list[Playbook]] = None,
        references: Optional[list[Reference]] = None,
    ) -> None:
        self._playbooks = playbooks or []
        self._references = references or []

    def build(
        self,
        session_id: str,
        workspace_id: str,
        results: list[ValidatorResult],
        rules: list[Rule],
        evidence_count: int = 0,
        duration_seconds: Optional[float] = None,
    ) -> TriageReport:
        """Build a complete triage report from validation results.

        :param session_id: Triage session identifier.
        :param workspace_id: Workspace identifier.
        :param results: Validation results from the rule validator.
        :param rules: Rules that were evaluated (for metadata lookup).
        :param evidence_count: Number of evidence artifacts collected.
        :param duration_seconds: Total analysis duration.
        :returns: Complete triage report.
        """
        rule_map = {r.id: r for r in rules}
        findings = self._build_findings(results, rule_map)
        summary = self._build_summary(findings, len(results))

        skipped = sum(1 for r in results if r.skipped)
        passed = sum(1 for r in results if r.passed and not r.skipped)

        return TriageReport(
            session_id=session_id,
            workspace_id=workspace_id,
            findings=findings,
            summary=summary,
            evidence_count=evidence_count,
            rules_evaluated=len(results),
            rules_passed=passed,
            rules_skipped=skipped,
            duration_seconds=duration_seconds,
        )

    def _build_findings(
        self,
        results: list[ValidatorResult],
        rule_map: dict[str, Rule],
    ) -> list[TriageFinding]:
        """Convert failed validation results into findings.

        Skipped results (missing evidence source) are excluded —
        they are tracked separately in the report counts.

        :param results: All validation results.
        :param rule_map: Lookup map for rule metadata.
        :returns: Findings for actual failures only.
        """
        findings: list[TriageFinding] = []
        for result in results:
            if result.passed or result.skipped:
                continue
            rule = rule_map.get(result.rule_id)
            finding = self._result_to_finding(result, rule)
            findings.append(finding)
        return findings

    def _result_to_finding(
        self,
        result: ValidatorResult,
        rule: Optional[Rule],
    ) -> TriageFinding:
        """Convert a single failed result into a TriageFinding.

        :param result: The failed validation result.
        :param rule: The rule that produced this result (if available).
        :returns: A TriageFinding.
        """
        if rule is not None:
            severity = _map_severity(rule.severity)
            failure_class = _classify_failure(rule)
            title = f"{rule.name}: {result.message}"
            description = rule.description
            playbook = self._match_playbook(rule)
            refs = self._match_references(rule)
        else:
            severity = Severity.MEDIUM
            failure_class = FailureClass.UNKNOWN
            title = result.message
            description = ""
            playbook = None
            refs = []

        return TriageFinding(
            finding_id=f"find-{uuid4().hex[:12]}",
            failure_class=failure_class,
            severity=severity,
            title=title,
            description=description,
            rule_id=result.rule_id,
            playbook_id=playbook.id if playbook else None,
            validator_results=[result.to_dict()],
            remediation=playbook.fixes if playbook else [],
            references=[r.url for r in refs] + rule.references if rule else [],
        )

    def _match_playbook(self, rule: Rule) -> Optional[Playbook]:
        """Find a playbook matching this rule's category and tags.

        :param rule: The rule to match.
        :returns: First matching playbook, or None.
        """
        rule_tags = {t.lower() for t in rule.tags}
        rule_category = rule.category.lower()

        for playbook in self._playbooks:
            pb_tags = {t.lower() for t in playbook.tags}
            if rule_tags & pb_tags:
                return playbook
            if rule_category and rule_category in playbook.category.lower():
                return playbook
        return None

    def _match_references(self, rule: Rule) -> list[Reference]:
        """Find references relevant to this rule.

        :param rule: The rule to match.
        :returns: Matching references.
        """
        rule_tags = {t.lower() for t in rule.tags}
        matched: list[Reference] = []
        for ref in self._references:
            ref_tags = {t.lower() for t in ref.tags}
            if rule_tags & ref_tags:
                matched.append(ref)
        return matched

    def _build_summary(self, findings: list[TriageFinding], total_rules: int) -> str:
        """Generate a human-readable summary.

        :param findings: The findings in the report.
        :param total_rules: Total rules evaluated.
        :returns: Summary string.
        """
        if not findings:
            return f"All {total_rules} rules passed. No issues found."

        by_severity: dict[str, int] = {}
        for f in findings:
            sev = f.severity if isinstance(f.severity, str) else f.severity
            by_severity[sev] = by_severity.get(sev, 0) + 1

        parts = [f"{len(findings)} issue(s) found from {total_rules} rules evaluated."]
        for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
            count = by_severity.get(sev, 0)
            if count:
                parts.append(f"{sev}: {count}")

        return " ".join(parts)
