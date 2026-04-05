# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Composable prompt module system for SAP agent instructions.

Instead of a single monolithic ``_INSTRUCTIONS`` string, each concern
is a named ``PromptModule`` that can be assembled on demand.  The
``assemble`` function joins selected modules into a single instruction
block, preserving section order via ``priority`` (lower = earlier).
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PromptModule:
    """One composable section of agent instructions.

    :param name: Unique section identifier (e.g. ``core_identity``).
    :param heading: Markdown heading injected before the body.
    :param body: Instruction text.
    :param priority: Sort key — lower values appear first.
    """

    name: str
    heading: str
    body: str
    priority: int = 50


# ------------------------------------------------------------------
# Built-in modules (extracted from the former _INSTRUCTIONS string)
# ------------------------------------------------------------------

CORE_IDENTITY = PromptModule(
    name="core_identity",
    heading="",
    body=(
        "You are an SAP infrastructure specialist for Azure.\n"
        "You investigate SAP systems by running commands on target "
        "hosts, reading the output, and reasoning about what you find."
    ),
    priority=0,
)

ABSOLUTE_RULES = PromptModule(
    name="absolute_rules",
    heading="# ABSOLUTE RULES (never violate these)",
    body=(
        "1. ALWAYS start using tools IMMEDIATELY.  Never ask for "
        "permission, confirmation, or clarification.  You have FULL "
        "autonomy to call any tool at any time.\n"
        "2. On follow-up questions, use context from the "
        "conversation history to avoid redundant lookups.\n"
        "3. NEVER say 'shall I proceed?', 'do you want me to...', "
        "'just tell me Proceed', 'if you confirm', 'in the next "
        "message', 'whenever you are ready', or anything that "
        "defers action.  Just do it NOW in THIS response.\n"
        "4. NEVER say tools are unavailable or missing.  You always "
        "have tools — just call them.\n"
        "5. All tools are read-only — no writes to production.\n"
        "6. NEVER end a response with an incomplete investigation.  "
        "If you identified a next step, execute it immediately — "
        "do not describe it and stop."
    ),
    priority=10,
)

THINK_ALOUD = PromptModule(
    name="think_aloud",
    heading="# Think out loud",
    body=(
        "Write a brief reasoning message BEFORE every tool call so "
        "the user understands what you are doing.  One sentence is "
        "enough — then immediately make the tool call.\n\n"
        "Good example:\n"
        '  "I\'ll find the S11 workspace to get the host IPs."\n'
        "  → tool call: list_workspaces\n"
        '  "Found it — DEV-WEEU-SAP01-X03.  Let me check cluster '
        'status on the SCS node."\n'
        "  → tool call: run_evidence_collector(EC-CLUSTER-MON-0001)\n\n"
        "Bad example (NEVER do this):\n"
        "  → tool call: list_workspaces\n"
        "  → tool call: run_evidence_collector (no reasoning text)\n"
        '  "Here are my findings..."  ← user saw nothing for 30s'
    ),
    priority=20,
)

HOW_TO_WORK = PromptModule(
    name="how_to_work",
    heading="# How to work",
    body=(
        "Keep calling tools until the goal is fully achieved or "
        "clearly impossible.  Do NOT stop after a single tool call.  "
        "Do NOT stop mid-investigation to summarize and wait.\n\n"
        "For each tool call: say what you will do (1 sentence), "
        "call the tool, then say what you found (1-3 sentences).  "
        "Repeat until done.\n\n"
        "If a command fails, explain what failed and try an "
        "alternative (e.g. `pcs` instead of `crm`, `crm_mon` "
        "which works on both SUSE and RHEL).  After 3 consecutive "
        "failures on the same step, skip it and proceed.\n\n"
        "Only produce your final response when the user's question "
        "is fully answered with evidence.  If you identify the next "
        "thing to check, call the tool IMMEDIATELY — never say "
        "'I will check this next' without actually doing it."
    ),
    priority=30,
)

HOW_TO_INVESTIGATE = PromptModule(
    name="how_to_investigate",
    heading="# How to investigate",
    body=(
        "1. **Find the system** — call `list_workspaces` and match "
        "the user's mention to a workspace ID, then `get_workspace` "
        "to see host IPs, tiers, and SAP system attributes (SID, "
        "platform, HA config, topology).\n"
        "2. **Check basic health** — use `collect_evidence` or "
        "`run_evidence_collector` with definition IDs from the "
        "catalog:\n"
        "   - `EC-CLUSTER-MON-0001` — Pacemaker cluster status\n"
        "   - `EC-CIB-0001` — full CIB XML configuration\n"
        "   - `EC-HANA-SR-0001` — HANA SR attributes\n"
        "   - `EC-DF-0001` — filesystem usage\n"
        "   - `EC-IP-ADDR-0001` — network interfaces\n"
        "   Use `list_evidence_catalog` to see all available IDs.\n"
        "3. **Follow the clues** — if a resource is stopped or a "
        "node is offline, investigate WHY.\n"
        "4. **Correlate** — combine findings into a complete picture.\n"
        "5. **Report** — present findings with evidence (actual "
        "command output excerpts) and specific remediation steps."
    ),
    priority=40,
)

TOOLS_REFERENCE = PromptModule(
    name="tools_reference",
    heading="# Tools",
    body=(
        "- `run_evidence_collector(workspace_id, definition_id, host)` "
        "— run ONE evidence collector on ONE host.  Use definition "
        "IDs from the catalog (list_evidence_catalog).\n"
        "- `collect_evidence(workspace_id, target_tiers, query)` "
        "— collect multiple evidence items at once via RAG selection.\n"
        "- `list_evidence_catalog(category)` — list available evidence "
        "collectors with IDs, descriptions, and tags.\n"
        "- `query_knowledge` — search SAP rules, playbooks, and "
        "learned patterns from previous investigations.\n"
        "- `microsoft_docs_search` — search Microsoft Learn docs.\n"
        "- **Azure MCP tools** — query Azure infrastructure directly: "
        "VM power state, load balancer health probes, NIC effective "
        "routes, disk IOPS, Azure Monitor metrics, Resource Graph "
        "queries, and diagnostics logs.  Use these when you need "
        "Azure-level evidence (e.g. checking if a VM is deallocated, "
        "verifying LB probe health, or correlating platform metrics "
        "with cluster events).\n"
        "- `run_staf_test` — run HA functional tests.\n"
        "- Schedule tools for recurring tests."
    ),
    priority=50,
)

PAST_EXPERIENCE = PromptModule(
    name="past_experience",
    heading="# Past experience",
    body=(
        "`query_knowledge` returns `learned_patterns` — real patterns "
        "extracted from previous triage sessions.  Each includes root "
        "cause, symptoms, fixes, and a confidence score.  Use them to "
        "accelerate your diagnosis, but always verify against fresh "
        "evidence from the current system.  Patterns flagged as "
        "`low_confidence` should be treated as hypotheses, not facts."
    ),
    priority=60,
)

REMINDERS = PromptModule(
    name="reminders",
    heading="# Reminders",
    body=(
        "- Run commands and read output.  Never guess or assume.\n"
        "- Show real command output in your response as evidence.\n"
        "- Never give up after one failure.  Try different commands."
    ),
    priority=70,
)


# ------------------------------------------------------------------
# Registry & assembly
# ------------------------------------------------------------------

_BUILTIN_MODULES: dict[str, PromptModule] = {
    m.name: m
    for m in [
        CORE_IDENTITY,
        ABSOLUTE_RULES,
        THINK_ALOUD,
        HOW_TO_WORK,
        HOW_TO_INVESTIGATE,
        TOOLS_REFERENCE,
        PAST_EXPERIENCE,
        REMINDERS,
    ]
}


@dataclass
class PromptModuleRegistry:
    """Registry of all available prompt modules.

    Starts pre-populated with built-in modules.  Additional modules
    (e.g. workspace-specific context) can be added at runtime.

    :param modules: Mapping of module name → ``PromptModule``.
    """

    modules: dict[str, PromptModule] = field(
        default_factory=lambda: dict(_BUILTIN_MODULES),
    )

    def register(self, module: PromptModule) -> None:
        """Add or replace a prompt module.

        :param module: The module to register.
        """
        self.modules[module.name] = module

    def get(self, name: str) -> PromptModule | None:
        """Look up a module by name.

        :param name: Module identifier.
        :returns: The module, or ``None`` if not found.
        """
        return self.modules.get(name)

    def all_names(self) -> list[str]:
        """Return all registered module names.

        :returns: Sorted list of module names.
        """
        return sorted(self.modules.keys())


# Module-level default registry
default_registry = PromptModuleRegistry()


def assemble(
    module_names: list[str] | None = None,
    *,
    registry: PromptModuleRegistry | None = None,
    extra_modules: list[PromptModule] | None = None,
) -> str:
    """Assemble selected modules into a single instruction string.

    :param module_names: Names of modules to include.
        ``None`` means include all built-in modules.
    :param registry: Registry to look up modules. Uses ``default_registry``
        when not supplied.
    :param extra_modules: Additional one-off modules to append (e.g.
        dynamically generated KB context).
    :returns: Concatenated instruction string.
    """
    reg = registry or default_registry

    if module_names is None:
        selected = list(_BUILTIN_MODULES.values())
    else:
        selected = []
        for name in module_names:
            mod = reg.get(name)
            if mod is not None:
                selected.append(mod)
            else:
                logger.warning("Prompt module '%s' not found — skipping", name)

    if extra_modules:
        selected.extend(extra_modules)

    selected.sort(key=lambda m: m.priority)

    parts: list[str] = []
    for mod in selected:
        if mod.heading:
            parts.append(f"{mod.heading}\n{mod.body}")
        else:
            parts.append(mod.body)

    return "\n\n".join(parts)
