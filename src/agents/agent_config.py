# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Intent-based agent configuration.

Defines ``InvestigationIntent`` — the *kind* of work the user is
requesting — and ``AgentConfig`` — a frozen configuration that tunes
agent behaviour (prompt modules, token budget, evidence thresholds)
for that intent.

Classification is handled by ``SapAgentFactory.classify_intent()``
which performs a lightweight LLM call with structured output.
"""

from __future__ import annotations
import enum
from dataclasses import dataclass, field

from src.agents.prompt_modules import (
    ABSOLUTE_RULES,
    CORE_IDENTITY,
    HOW_TO_INVESTIGATE,
    HOW_TO_WORK,
    PAST_EXPERIENCE,
    REMINDERS,
    THINK_ALOUD,
    TOOLS_REFERENCE,
)


class InvestigationIntent(enum.Enum):
    """High-level intent categories for SAP agent conversations.

    :cvar TRIAGE: Investigate a live system issue.
    :cvar TEST: Run or schedule a STAF/HA test.
    :cvar KNOWLEDGE: Ask about SAP rules, notes, or best practices.
    :cvar GENERAL: Conversational / unclassifiable.
    """

    TRIAGE = "triage"
    TEST = "test"
    KNOWLEDGE = "knowledge"
    GENERAL = "general"


@dataclass(frozen=True)
class AgentConfig:
    """Frozen configuration that tunes agent behaviour per intent.

    :param intent: The classified investigation intent.
    :param module_names: Prompt modules to include in instructions.
    :param max_rounds: Maximum agent tool-call iterations.
    :param token_budget: Token budget for compaction.
    :param inject_kb: Whether to inject proactive KB context.
    """

    intent: InvestigationIntent
    module_names: list[str] = field(default_factory=list)
    max_rounds: int = 75
    token_budget: int = 120_000
    inject_kb: bool = False


# ------------------------------------------------------------------
# Pre-built configurations per intent
# ------------------------------------------------------------------

_ALL_MODULES = [
    CORE_IDENTITY.name,
    ABSOLUTE_RULES.name,
    THINK_ALOUD.name,
    HOW_TO_WORK.name,
    HOW_TO_INVESTIGATE.name,
    TOOLS_REFERENCE.name,
    PAST_EXPERIENCE.name,
    REMINDERS.name,
]

TRIAGE_CONFIG = AgentConfig(
    intent=InvestigationIntent.TRIAGE,
    module_names=list(_ALL_MODULES),
    max_rounds=75,
    token_budget=120_000,
    inject_kb=True,
)

TEST_CONFIG = AgentConfig(
    intent=InvestigationIntent.TEST,
    module_names=[
        CORE_IDENTITY.name,
        ABSOLUTE_RULES.name,
        THINK_ALOUD.name,
        HOW_TO_WORK.name,
        TOOLS_REFERENCE.name,
        REMINDERS.name,
    ],
    max_rounds=50,
    token_budget=80_000,
    inject_kb=False,
)

KNOWLEDGE_CONFIG = AgentConfig(
    intent=InvestigationIntent.KNOWLEDGE,
    module_names=[
        CORE_IDENTITY.name,
        ABSOLUTE_RULES.name,
        THINK_ALOUD.name,
        HOW_TO_WORK.name,
        TOOLS_REFERENCE.name,
        PAST_EXPERIENCE.name,
        REMINDERS.name,
    ],
    max_rounds=30,
    token_budget=60_000,
    inject_kb=True,
)

GENERAL_CONFIG = AgentConfig(
    intent=InvestigationIntent.GENERAL,
    module_names=[
        CORE_IDENTITY.name,
        ABSOLUTE_RULES.name,
        THINK_ALOUD.name,
        HOW_TO_WORK.name,
        TOOLS_REFERENCE.name,
        REMINDERS.name,
    ],
    max_rounds=30,
    token_budget=60_000,
    inject_kb=False,
)

_INTENT_CONFIGS: dict[InvestigationIntent, AgentConfig] = {
    InvestigationIntent.TRIAGE: TRIAGE_CONFIG,
    InvestigationIntent.TEST: TEST_CONFIG,
    InvestigationIntent.KNOWLEDGE: KNOWLEDGE_CONFIG,
    InvestigationIntent.GENERAL: GENERAL_CONFIG,
}


def config_for_intent(intent: InvestigationIntent) -> AgentConfig:
    """Return the pre-built ``AgentConfig`` for *intent*.

    :param intent: Investigation intent.
    :returns: Matching agent configuration.
    """
    return _INTENT_CONFIGS[intent]
