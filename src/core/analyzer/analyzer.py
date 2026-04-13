# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Analyzer facade — orchestrates normalizers, validators, and report assembly.

This is the top-level entry point for Phase 3. It does NOT import from
``src.core.execution`` — it reads ``EvidenceArtifact`` objects directly.
"""

import logging
import time
from typing import Optional

from src.core.analyzer.normalizers import NormalizedData, NormalizerRegistry
from src.core.analyzer.report import ReportBuilder
from src.core.analyzer.validators import RuleValidator
from src.core.models.evidence import EvidenceArtifact, EvidenceType
from src.core.models.knowledge import Rule
from src.core.models.triage import TriageReport, TriageSession
from src.core.models.validators import ValidatorResult

logger = logging.getLogger(__name__)


class Analyzer:
    """
    Facade that orchestrates the analysis pipeline.

    :param normalizer_registry: Maps source types to normalizers.
    :param rule_validator: Evaluates rules against normalized data.
    :param report_builder: Assembles findings into a report.
    """

    def __init__(
        self,
        normalizer_registry: Optional[NormalizerRegistry] = None,
        rule_validator: Optional[RuleValidator] = None,
        report_builder: Optional[ReportBuilder] = None,
    ) -> None:
        self._registry = normalizer_registry or NormalizerRegistry.default()
        self._validator = rule_validator or RuleValidator()
        self._report_builder = report_builder or ReportBuilder()

    @property
    def normalizer_registry(self) -> NormalizerRegistry:
        """The normalizer registry used by this analyzer."""
        return self._registry

    @property
    def rule_validator(self) -> RuleValidator:
        """The rule validator used by this analyzer."""
        return self._validator

    @property
    def report_builder(self) -> ReportBuilder:
        """The report builder used by this analyzer."""
        return self._report_builder

    def analyze(
        self,
        session: TriageSession,
        artifacts: list[EvidenceArtifact],
        rules: list[Rule],
    ) -> TriageReport:
        """
        Run the full analysis pipeline.

        :param session: The triage session (must be in ANALYZING state).
        :param artifacts: Collected evidence artifacts.
        :param rules: Rules to evaluate.
        :returns: Complete triage report.
        """
        start = time.monotonic()
        session_id = str(session.id)

        logger.info(
            "Analyzer: session %s — %d artifacts, %d rules",
            session_id,
            len(artifacts),
            len(rules),
        )

        usable = self._filter_usable(artifacts)
        data_map = self._normalize_all(usable)

        applicable_rules = self._filter_rules_with_evidence(rules, data_map)
        results = self._validator.validate_many(applicable_rules, data_map)

        duration = time.monotonic() - start
        report = self._report_builder.build(
            session_id=session_id,
            workspace_id=session.workspace_id,
            results=results,
            rules=applicable_rules,
            evidence_count=len(artifacts),
            duration_seconds=round(duration, 3),
        )

        session.complete_analysis(report)

        logger.info(
            "Analyzer: session %s — %d findings from %d rules in %.3fs",
            session_id,
            report.finding_count,
            len(applicable_rules),
            duration,
        )

        return report

    def analyze_artifacts(
        self,
        artifacts: list[EvidenceArtifact],
        rules: list[Rule],
    ) -> tuple[list[ValidatorResult], dict[str, NormalizedData]]:
        """Run normalization + validation without session state management.

        :param artifacts: Evidence artifacts to analyze.
        :param rules: Rules to evaluate.
        :returns: Tuple of (results, normalized_data_map).
        """
        usable = self._filter_usable(artifacts)
        data_map = self._normalize_all(usable)
        applicable = self._filter_rules_with_evidence(rules, data_map)
        results = self._validator.validate_many(applicable, data_map)
        return results, data_map

    def _filter_usable(self, artifacts: list[EvidenceArtifact]) -> list[EvidenceArtifact]:
        """Filter to only usable (successful) artifacts."""
        usable = [a for a in artifacts if a.is_usable]
        skipped = len(artifacts) - len(usable)
        if skipped:
            logger.info("Skipped %d non-usable artifacts", skipped)
        return usable

    def _normalize_all(self, artifacts: list[EvidenceArtifact]) -> dict[str, NormalizedData]:
        """
        Normalize all artifacts, keyed by evidence source type.

        :param artifacts: Usable evidence artifacts.
        :returns: Mapping of source name → normalized data.
        """
        data_map: dict[str, NormalizedData] = {}

        for artifact in artifacts:
            source = artifact.metadata.get("source", "")
            if not source:
                source = self._infer_source(artifact)
            normalizer = self._registry.get(source)
            if normalizer is None:
                logger.debug(
                    "No normalizer for source '%s' (artifact %s)",
                    source,
                    artifact.evidence_id,
                )
                continue
            self._merge_data(data_map, source, normalizer.normalize(artifact))

            for peer in self._registry.get_peer_sources(source):
                if peer != source and peer not in data_map:
                    peer_normalizer = self._registry.get(peer)
                    if peer_normalizer is not None:
                        peer_data = peer_normalizer.normalize(artifact)
                        self._merge_data(data_map, peer, peer_data)

        return data_map

    @staticmethod
    def _merge_data(
        data_map: dict[str, NormalizedData],
        source: str,
        normalized: NormalizedData,
    ) -> None:
        """Merge normalized data into the data map.

        :param data_map: Target data map.
        :param source: Source key.
        :param normalized: Data to merge.
        """
        existing = data_map.get(source)
        if existing is not None:
            existing.values.update(normalized.values)
        else:
            data_map[source] = normalized

    def _infer_source(self, artifact: EvidenceArtifact) -> str:
        """Infer the source from artifact evidence type.

        In an agentic/MCP architecture, source metadata should be set
        :returns: Inferred source name.
        """
        if artifact.evidence_type == EvidenceType.CIB_XML:
            return "cib_resource"
        if artifact.evidence_type == EvidenceType.LOG_EXCERPT:
            return "log"

        return "command"

    def _filter_rules_with_evidence(
        self,
        rules: list[Rule],
        data_map: dict[str, NormalizedData],
    ) -> list[Rule]:
        """Keep only rules whose evidence source AND parameter are available.

        :param rules: All candidate rules.
        :param data_map: Available normalized evidence.
        :returns: Rules that can be evaluated.
        """
        evaluable: list[Rule] = []
        skipped_source = 0
        skipped_param = 0

        for rule in rules:
            source = rule.validator.source if rule.validator else ""
            if not source:
                evaluable.append(rule)
                continue
            data = data_map.get(source)
            if data is None:
                skipped_source += 1
                continue
            param = rule.validator.parameter if rule.validator else ""
            if param and data.get(param) is None:
                skipped_param += 1
                continue
            evaluable.append(rule)

        if skipped_source or skipped_param:
            logger.info(
                "Skipped %d rules (no source) + %d rules (parameter not in evidence)",
                skipped_source,
                skipped_param,
            )

        return evaluable
