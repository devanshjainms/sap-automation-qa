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
    THINK_OUT_LOUD,
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
    "You are the entry point. Your ONLY job is to route:\n"
    "1. Read the user's request.\n"
    "2. Hand off IMMEDIATELY to the right specialist:\n"
    "   - **Investigator** for troubleshooting, diagnostics, "
    "health checks, and configuration review.\n"
    "   - **TestRunner** for running HA/functional tests.\n"
    "3. Do NOT call any tools yourself — let the specialist do it.\n"
    "4. After the specialist returns, present the findings "
    "to the user with evidence and remediation steps.\n\n"
    "NEVER call `list_workspaces`, `get_workspace`, `collect_evidence`, "
    "or any investigation tools. That is the Investigator's job.\n\n"
    "**CRITICAL: Produce exactly ONE final summary.** "
    "Do NOT repeat findings you have already presented. "
    "If you have already delivered the investigation results, STOP. "
    "Do NOT produce another summary or re-state your conclusion."
)

INVESTIGATOR_SPEC = SpecialistConfig(
    name="Investigator",
    description="Collects evidence and analyzes SAP system health.",
    module_names=[
        CORE_IDENTITY.name,
        ABSOLUTE_RULES.name,
        HOW_TO_WORK.name,
        THINK_OUT_LOUD.name,
        HOW_TO_INVESTIGATE.name,
        TOOLS_REFERENCE.name,
        PAST_EXPERIENCE.name,
        REMINDERS.name,
    ],
    role_prompt=(
        "\n\n**ROLE: INVESTIGATOR**\n"
        "You own the full investigation lifecycle:\n\n"
        "**Preferred: Use the `sap-triage` skill** (if available):\n"
        "1. `load_skill('sap-triage')` to get instructions.\n"
        "2. `read_skill_resource('sap-triage', 'workspaces')` to find "
        "the target system.\n"
        "3. `run_skill_script('sap-triage', 'investigate', "
        "{workspace_id, query})` for a full investigation in one call.\n\n"
        "**Fallback: Use MCP tools** (if skills are unavailable):\n"
        "1. **Find the system** — call `list_workspaces` + `get_workspace` "
        "to identify the target.\n"
        "2. **Collect evidence** — use `collect_evidence`, "
        "`run_evidence_collector`, or `search_logs`.\n"
        "3. **Read artifacts** — use `get_evidence_output` to read "
        "the actual command output.\n"
        "4. **Analyze** — call `run_analysis` to check against rules.\n"
        "5. **Diagnose** — form your conclusion with evidence.\n\n"
        "Keep reasoning brief between tool calls (1-2 sentences).\n"
        "Save your complete diagnosis for the FINAL handoff.\n\n"
        "All evidence collection tools are read-only — proceed "
        "autonomously without asking for user approval.\n\n"
        "When done, hand back to the Coordinator with your "
        "complete findings and diagnosis.\n\n"
        "NEVER hand back to the Coordinator without having called "
        "at least one evidence collection tool. You MUST investigate "
        "before returning."
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
        "You run HA functional tests on SAP systems.\n\n"
        "**Preferred: Use the `sap-staf-test` skill** (if available):\n"
        "1. `load_skill('sap-staf-test')` to get instructions.\n"
        "2. `read_skill_resource('sap-staf-test', 'test-catalog')` to see "
        "available tests.\n"
        "3. `run_skill_script('sap-staf-test', 'run_test', "
        "{workspace_id, test_group, test_ids})` for end-to-end execution.\n\n"
        "**Fallback: Use MCP tools** (if skills are unavailable):\n"
        "For each test:\n"
        "1. Explain which test you're running and why.\n"
        "2. Call `run_staf_test` — the system will automatically "
        "ask the user for approval before executing.\n"
        "3. If the user rejects, skip that test and explain what "
        "you would have done.\n"
        "4. Analyze the test result.\n"
        "5. If the test failed, investigate why before moving on.\n\n"
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
    coordinator_turn_limit: int = 5
    specialists: tuple[SpecialistConfig, ...] = ()


_ALL_MODULES = [
    CORE_IDENTITY.name,
    ABSOLUTE_RULES.name,
    HOW_TO_WORK.name,
    THINK_OUT_LOUD.name,
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
    coordinator_turn_limit=5,
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
    coordinator_turn_limit=5,
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
