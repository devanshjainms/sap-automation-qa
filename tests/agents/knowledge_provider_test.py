# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for KnowledgeContextProvider."""

from __future__ import annotations
from pytest_mock import MockerFixture
import pytest
from src.agents.providers.knowledge_provider import (
    KnowledgeContextProvider,
    _MIN_SCORE,
)
from src.core.knowledge.retrieval import ScoredResult


def _scored(mocker: MockerFixture, item_type: str, score: float, **kwargs) -> ScoredResult:
    """Build a minimal ``ScoredResult`` with the given score."""
    item = mocker.MagicMock()
    item.id = kwargs.get("item_id", f"{item_type}_001")
    item.name = kwargs.get("name", f"Some {item_type}")
    item.description = kwargs.get("description", "desc")
    item.severity = kwargs.get("severity", "high")
    item.symptoms = kwargs.get("symptoms", ["symptom1"])
    item.fixes = kwargs.get("fixes", ["fix1"])
    item.confidence = kwargs.get("confidence", 0.8)
    item.tags = kwargs.get("tags", [])
    return ScoredResult(
        item_id=item.id,
        item_type=item_type,
        score=score,
        relevance=score,
        confidence=kwargs.get("confidence", 1.0),
        recency=1.0,
        item=item,
        low_confidence=kwargs.get("low_confidence", False),
    )


def _make_retriever(
    mocker: MockerFixture,
    rules: list[ScoredResult] | None = None,
    playbooks: list[ScoredResult] | None = None,
    patterns: list[ScoredResult] | None = None,
):
    """Build a mock ``HybridRetriever``."""
    retriever = mocker.MagicMock()
    retriever.search_rules.return_value = rules or []
    retriever.search_playbooks.return_value = playbooks or []
    retriever.search_learned_patterns.return_value = patterns or []
    return retriever


class TestKnowledgeContextProvider:
    """Tests for the knowledge context provider."""

    @pytest.mark.asyncio
    async def test_empty_query_no_input_messages_does_not_inject(
        self, mocker: MockerFixture
    ) -> None:
        retriever = _make_retriever(mocker)
        provider = KnowledgeContextProvider(retriever=retriever)
        context = mocker.MagicMock()
        context.input_messages = []

        await provider.before_run(
            agent=mocker.MagicMock(),
            session=mocker.MagicMock(),
            context=context,
            state={},
        )

        context.extend_instructions.assert_not_called()
        retriever.search_rules.assert_not_called()

    @pytest.mark.asyncio
    async def test_extracts_query_from_input_messages(self, mocker: MockerFixture) -> None:
        """When user_query is None, extract from context.input_messages."""
        rules = [_scored(mocker, "rule", 0.8, name="failover rule", severity="high")]
        retriever = _make_retriever(mocker, rules=rules)
        provider = KnowledgeContextProvider(retriever=retriever)

        user_msg = mocker.MagicMock()
        user_msg.role = "user"
        user_msg.text = "HANA failover last night"

        context = mocker.MagicMock()
        context.input_messages = [user_msg]

        await provider.before_run(
            agent=mocker.MagicMock(),
            session=mocker.MagicMock(),
            context=context,
            state={},
        )

        context.extend_instructions.assert_called_once()
        retriever.search_rules.assert_called_once()
        assert retriever.search_rules.call_args[1]["query"] == "HANA failover last night"

    @pytest.mark.asyncio
    async def test_no_results_does_not_inject(self, mocker: MockerFixture) -> None:
        retriever = _make_retriever(mocker)
        provider = KnowledgeContextProvider(retriever=retriever, user_query="HANA failover")
        context = mocker.MagicMock()

        await provider.before_run(
            agent=mocker.MagicMock(),
            session=mocker.MagicMock(),
            context=context,
            state={},
        )

        context.extend_instructions.assert_not_called()

    @pytest.mark.asyncio
    async def test_rules_injected(self, mocker: MockerFixture) -> None:
        rules = [_scored(mocker, "rule", 0.8, name="sysctl check", severity="critical")]
        retriever = _make_retriever(mocker, rules=rules)
        provider = KnowledgeContextProvider(retriever=retriever, user_query="kernel parameters")
        context = mocker.MagicMock()

        await provider.before_run(
            agent=mocker.MagicMock(),
            session=mocker.MagicMock(),
            context=context,
            state={},
        )

        context.extend_instructions.assert_called_once()
        injected_text = context.extend_instructions.call_args[0][1]
        assert "Matching rules" in injected_text
        assert "sysctl check" in injected_text

    @pytest.mark.asyncio
    async def test_playbooks_injected(self, mocker: MockerFixture) -> None:
        playbooks = [
            _scored(
                mocker,
                "playbook",
                0.7,
                name="HANA failover playbook",
                symptoms=["node offline", "resource stopped"],
            )
        ]
        retriever = _make_retriever(mocker, playbooks=playbooks)
        provider = KnowledgeContextProvider(retriever=retriever, user_query="node offline")
        context = mocker.MagicMock()

        await provider.before_run(
            agent=mocker.MagicMock(),
            session=mocker.MagicMock(),
            context=context,
            state={},
        )

        context.extend_instructions.assert_called_once()
        injected_text = context.extend_instructions.call_args[0][1]
        assert "Matching playbooks" in injected_text
        assert "HANA failover playbook" in injected_text

    @pytest.mark.asyncio
    async def test_patterns_injected(self, mocker: MockerFixture) -> None:
        patterns = [
            _scored(
                mocker,
                "learned_pattern",
                0.6,
                name="Split brain after fence",
                symptoms=["split brain"],
                fixes=["restart pacemaker"],
                confidence=0.9,
            )
        ]
        retriever = _make_retriever(mocker, patterns=patterns)
        provider = KnowledgeContextProvider(retriever=retriever, user_query="split brain")
        context = mocker.MagicMock()

        await provider.before_run(
            agent=mocker.MagicMock(),
            session=mocker.MagicMock(),
            context=context,
            state={},
        )

        context.extend_instructions.assert_called_once()
        injected_text = context.extend_instructions.call_args[0][1]
        assert "Learned patterns" in injected_text
        assert "Split brain after fence" in injected_text

    @pytest.mark.asyncio
    async def test_low_score_results_filtered_out(self, mocker: MockerFixture) -> None:
        """Results below _MIN_SCORE are excluded."""
        rules = [_scored(mocker, "rule", _MIN_SCORE - 0.01)]
        retriever = _make_retriever(mocker, rules=rules)
        provider = KnowledgeContextProvider(retriever=retriever, user_query="test")
        context = mocker.MagicMock()

        await provider.before_run(
            agent=mocker.MagicMock(),
            session=mocker.MagicMock(),
            context=context,
            state={},
        )

        context.extend_instructions.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_sections_combined(self, mocker: MockerFixture) -> None:
        """Rules, playbooks, and patterns appear in one injection."""
        rules = [_scored(mocker, "rule", 0.5)]
        playbooks = [_scored(mocker, "playbook", 0.5)]
        patterns = [_scored(mocker, "learned_pattern", 0.5, confidence=0.8)]
        retriever = _make_retriever(mocker, rules=rules, playbooks=playbooks, patterns=patterns)
        provider = KnowledgeContextProvider(retriever=retriever, user_query="cluster")
        context = mocker.MagicMock()

        await provider.before_run(
            agent=mocker.MagicMock(),
            session=mocker.MagicMock(),
            context=context,
            state={},
        )

        injected_text = context.extend_instructions.call_args[0][1]
        assert "Matching rules" in injected_text
        assert "Matching playbooks" in injected_text
        assert "Learned patterns" in injected_text

    @pytest.mark.asyncio
    async def test_source_id_is_knowledge_context(self, mocker: MockerFixture) -> None:
        rules = [_scored(mocker, "rule", 0.5)]
        retriever = _make_retriever(mocker, rules=rules)
        provider = KnowledgeContextProvider(retriever=retriever, user_query="test")
        context = mocker.MagicMock()

        await provider.before_run(
            agent=mocker.MagicMock(),
            session=mocker.MagicMock(),
            context=context,
            state={},
        )

        source_id = context.extend_instructions.call_args[0][0]
        assert source_id == "knowledge-context"

    @pytest.mark.asyncio
    async def test_low_confidence_pattern_flagged(self, mocker: MockerFixture) -> None:
        patterns = [
            _scored(
                mocker,
                "learned_pattern",
                0.5,
                name="Weak pattern",
                confidence=0.3,
                low_confidence=True,
            )
        ]
        retriever = _make_retriever(mocker, patterns=patterns)
        provider = KnowledgeContextProvider(retriever=retriever, user_query="test")
        context = mocker.MagicMock()

        await provider.before_run(
            agent=mocker.MagicMock(),
            session=mocker.MagicMock(),
            context=context,
            state={},
        )

        injected_text = context.extend_instructions.call_args[0][1]
        assert "low confidence" in injected_text
