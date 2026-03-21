# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
CBR Extract — deterministic pattern extraction from triage sessions.

After a triage session completes, ``CbrExtract`` builds a
``LearnedPattern`` from the structured findings so the
``LearningPipeline`` can consolidate, revise, and store it.
"""

from __future__ import annotations
import logging
from uuid import uuid4
from src.core.models.knowledge import LearnedPattern
from src.core.models.triage import TriageReport

logger = logging.getLogger(__name__)


class CbrExtract:
    """Extract a ``LearnedPattern`` from a completed triage session.

    Uses deterministic extraction from structured findings.
    """

    @staticmethod
    def extract(
        report: TriageReport,
        query: str = "",
    ) -> LearnedPattern:
        """
        Extract a learned pattern from a triage report.

        :param report: Completed triage report.
        :param query: Original user query.
        :returns: A ``LearnedPattern`` candidate for the learning pipeline.
        """
        fixes = []
        for f in report.findings:
            fixes.extend(f.remediation)
        return LearnedPattern(
            id=f"LP-{uuid4().hex[:8].upper()}",
            name=query[:80] if query else f"Session {report.session_id[:8]}",
            description=report.summary or f"Pattern from {report.finding_count} findings",
            category=next(
                iter({str(f.failure_class) for f in report.findings if f.failure_class}), "general"
            ),
            symptoms=[f.title for f in report.findings if f.title][:10],
            investigation=[],
            root_cause="",
            fixes=list(dict.fromkeys(fixes))[:10],
            tags=[],
            source="learned",
            confidence=0.0,
            source_sessions=[report.session_id],
        )
