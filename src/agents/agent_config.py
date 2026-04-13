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
class SpecialistConfig:
    """Configuration for a specialist agent in a handoff workflow.

    :param name: Agent name (used in HandoffBuilder routing).
    :param description: Brief agent description.
    :param module_names: Prompt modules for this specialist's instructions.
    :param role_prompt: Additional role-specific instruction text
        appended after the assembled prompt modules.
    """

    name: str
    description: str
    module_names: list[str] = field(default_factory=list)
    role_prompt: str = ""


COORDINATOR_ROLE_PROMPT = (
    "\n\n**ROLE: COORDINATOR**\n"
    "You are the entry point. Your job:\n"
    "1. Identify the target SAP system — call "
    "`list_workspaces` and `get_workspace`.\n"
    "2. Understand the user's request.\n"
    "3. Hand off to the right specialist:\n"
    "   - **Investigator** for troubleshooting, diagnostics, "
    "health checks, and configuration review.\n"
    "   - **TestRunner** for running HA/functional tests.\n"
    "4. After the specialist returns, present the findings "
    "to the user with evidence and remediation steps.\n\n"
    "NEVER ask the user for confirmation. Just route and go."
)

INVESTIGATOR_SPEC = SpecialistConfig(
    name="Investigator",
    description="Collects evidence and analyzes SAP system health.",
    module_names=[
        CORE_IDENTITY.name,
        ABSOLUTE_RULES.name,
        HOW_TO_WORK.name,
        HOW_TO_INVESTIGATE.name,
        TOOLS_REFERENCE.name,
        PAST_EXPERIENCE.name,
        REMINDERS.name,
    ],
    role_prompt=(
        "\n\n**ROLE: INVESTIGATOR**\n"
        "You investigate SAP system issues step by step.\n"
        "For each step:\n"
        "1. Explain what you're about to check and why.\n"
        "2. Call the tool.\n"
        "3. Analyze the result — what does it tell you?\n"
        "4. Decide: need more evidence, or ready to conclude?\n\n"
        "When done, hand back to the Coordinator with your "
        "complete findings and diagnosis.\n\n"
        "NEVER ask the user whether to continue — always continue "
        "autonomously until you have a complete evidence-based answer."
    ),
)

TEST_RUNNER_SPEC = SpecialistConfig(
    name="TestRunner",
    description="Runs SAP HA and functional tests.",
    module_names=[
        CORE_IDENTITY.name,
        ABSOLUTE_RULES.name,
        HOW_TO_WORK.name,
        TOOLS_REFERENCE.name,
        REMINDERS.name,
    ],
    role_prompt=(
        "\n\n**ROLE: TEST RUNNER**\n"
        "You run HA functional tests on SAP systems.\n"
        "For each test:\n"
        "1. Explain which test you're running and why.\n"
        "2. Call `run_staf_test` or the appropriate test tool.\n"
        "3. Analyze the test result.\n"
        "4. If the test failed, investigate why before moving on.\n\n"
        "When done, hand back to the Coordinator with test "
        "results and any issues found."
    ),
)


@dataclass(frozen=True)
class AgentConfig:
    """Frozen configuration that tunes agent behaviour per intent.

    :param intent: The classified investigation intent.
    :param module_names: Prompt modules to include in instructions.
    :param max_rounds: Maximum agent tool-call iterations.
    :param token_budget: Token budget for compaction.
    :param inject_kb: Whether to inject proactive KB context.
    :param coordinator_turn_limit: Max autonomous turns for the
        coordinator in handoff workflows.
    :param specialists: Specialist configs for handoff workflows.
        Empty for single-agent intents.
    """

    intent: InvestigationIntent
    module_names: list[str] = field(default_factory=list)
    max_rounds: int = 75
    token_budget: int = 120_000
    inject_kb: bool = False
    coordinator_turn_limit: int = 10
    specialists: tuple[SpecialistConfig, ...] = ()


_ALL_MODULES = [
    CORE_IDENTITY.name,
    ABSOLUTE_RULES.name,
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
    coordinator_turn_limit=10,
    specialists=(INVESTIGATOR_SPEC, TEST_RUNNER_SPEC),
)

TEST_CONFIG = AgentConfig(
    intent=InvestigationIntent.TEST,
    module_names=[
        CORE_IDENTITY.name,
        ABSOLUTE_RULES.name,
        HOW_TO_WORK.name,
        TOOLS_REFERENCE.name,
        REMINDERS.name,
    ],
    max_rounds=50,
    token_budget=80_000,
    inject_kb=False,
    coordinator_turn_limit=10,
    specialists=(INVESTIGATOR_SPEC, TEST_RUNNER_SPEC),
)

KNOWLEDGE_CONFIG = AgentConfig(
    intent=InvestigationIntent.KNOWLEDGE,
    module_names=[
        CORE_IDENTITY.name,
        ABSOLUTE_RULES.name,
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
