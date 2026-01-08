# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
SAP Domain Glossary Plugin - LEAN Version.
"""

import json
import re
from typing import Annotated, Dict, List, Optional, Any

from semantic_kernel.functions import kernel_function

from src.agents.observability import get_logger

logger = get_logger(__name__)


INPUT_PATTERNS: Dict[str, Dict[str, Any]] = {
    "SID": {
        "regex": r"^[A-Z][A-Z0-9]{2}$",
        "description": "SAP System ID - 3 alphanumeric characters starting with letter",
        "examples": ["X01", "X00", "PRD", "QAS"],
    },
    "WORKSPACE_ID": {
        "regex": r"^(DEV|QA|PROD)-[A-Z]{4}-SAP\d{2}-[A-Z][A-Z0-9]{2}$",
        "description": "Workspace format: ENV-REGION-DEPLOYMENT-SID",
        "examples": ["QA-WEEU-SAP01-X01", "PROD-EAUS-SAP01-P01"],
    },
    "IP_ADDRESS": {
        "regex": r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$",
        "description": "IPv4 address",
    },
}

PROJECT_ABBREVIATIONS: Dict[str, str] = {
    "AFA": "Azure Fence Agent - STONITH via Azure API",
    "SBD": "STONITH Block Device - disk-based fencing",
    "HSR": "HANA System Replication",
    "WEEU": "West Europe (Azure region code)",
    "EAUS": "East US (Azure region code)",
    "WEUS": "West US (Azure region code)",
}

TEST_GROUP_ALIASES: Dict[str, str] = {
    "database": "HA_DB_HANA",
    "db": "HA_DB_HANA",
    "hana": "HA_DB_HANA",
    "hana tests": "HA_DB_HANA",
    "hana ha": "HA_DB_HANA",
    "hana failover": "HA_DB_HANA",
    "database ha": "HA_DB_HANA",
    "database failover": "HA_DB_HANA",
    "db failover": "HA_DB_HANA",
    "db ha": "HA_DB_HANA",
    "hana replication": "HA_DB_HANA",
    "hsr": "HA_DB_HANA",
    "ha_db_hana": "HA_DB_HANA",
    "central services": "HA_SCS",
    "scs": "HA_SCS",
    "ascs": "HA_SCS",
    "ers": "HA_SCS",
    "ascs/ers": "HA_SCS",
    "enqueue": "HA_SCS",
    "enqueue replication": "HA_SCS",
    "ensa": "HA_SCS",
    "ensa2": "HA_SCS",
    "scs failover": "HA_SCS",
    "scs ha": "HA_SCS",
    "central services ha": "HA_SCS",
    "ha_scs": "HA_SCS",
    "all": "ALL",
    "both": "ALL",
    "everything": "ALL",
    "full": "ALL",
    "complete": "ALL",
}

TEST_GROUP_FRIENDLY_NAMES: Dict[str, str] = {
    "HA_DB_HANA": "Database/HANA HA Tests",
    "HA_SCS": "Central Services (ASCS/ERS) HA Tests",
    "CONFIG_CHECKS": "Configuration Validation (read-only)",
    "HA_OFFLINE": "Offline HA Validation",
}


class GlossaryPlugin:
    """
    Lean plugin for pattern recognition and disambiguation.

    PURPOSE:
    - Identify patterns in user input (SID, workspace ID, IP)
    - Resolve ambiguous references to concrete workspace paths
    - Provide project-specific abbreviation lookups

    NOT FOR:
    - General SAP knowledge (use LLM's training or web_search)
    - Command references (LLM knows or can discover)
    - Static configuration (use tools to read dynamically)
    """

    def __init__(self) -> None:
        logger.info("GlossaryPlugin initialized (lean mode)")

    @kernel_function(
        name="identify_pattern",
        description="Identify what type of input the user provided. "
        "Use this when user mentions something short like 'X01', 'X00' that could be a SID, "
        "or a full workspace ID, or an IP address. Returns the pattern type.",
    )
    def identify_pattern(
        self,
        text: Annotated[str, "The text to analyze (e.g., 'X01', '10.0.0.1')"],
    ) -> Annotated[str, "JSON with identified pattern type and details"]:
        """Identify what type of input the user provided."""
        text = text.strip().upper()

        for pattern_name, pattern_info in INPUT_PATTERNS.items():
            if re.match(pattern_info["regex"], text):
                return json.dumps(
                    {
                        "input": text,
                        "pattern_type": pattern_name,
                        "description": pattern_info["description"],
                        "is_likely_sid": pattern_name == "SID",
                        "next_action": (
                            "Use resolve_user_reference to find matching workspace"
                            if pattern_name == "SID"
                            else "Input identified"
                        ),
                    }
                )

        return json.dumps(
            {
                "input": text,
                "pattern_type": "UNKNOWN",
                "suggestion": "Could not identify pattern. May be a hostname, resource name, or free text.",
            }
        )

    @kernel_function(
        name="resolve_user_reference",
        description="CRITICAL: When user mentions a SID like 'X01' or 'X00', use this to find "
        "the matching workspace. Searches available workspaces and returns the full workspace "
        "path that contains this SID. Call this BEFORE asking 'What is X01?'",
    )
    def resolve_user_reference(
        self,
        reference: Annotated[str, "The user's reference to resolve (e.g., 'X01', 'X00')"],
        available_workspaces: Annotated[
            str,
            "Comma-separated list of available workspaces (from list_workspaces tool)",
        ],
    ) -> Annotated[str, "JSON with resolved workspace or suggestions"]:
        """Resolve an ambiguous user reference to a concrete workspace."""
        reference = reference.strip().upper()
        workspaces = [w.strip() for w in available_workspaces.split(",")]

        matches = []
        for ws in workspaces:
            if ws.upper().endswith(f"-{reference}"):
                matches.append(ws)
            elif ws.upper() == reference:
                matches.append(ws)
            elif reference in ws.upper():
                matches.append(ws)

        if len(matches) == 1:
            return json.dumps(
                {
                    "reference": reference,
                    "resolved": True,
                    "workspace": matches[0],
                    "message": f"'{reference}' resolved to workspace '{matches[0]}'",
                }
            )
        elif len(matches) > 1:
            return json.dumps(
                {
                    "reference": reference,
                    "resolved": False,
                    "candidates": matches,
                    "message": f"Multiple workspaces match '{reference}'. Ask user to clarify.",
                }
            )
        else:
            return json.dumps(
                {
                    "reference": reference,
                    "resolved": False,
                    "candidates": [],
                    "message": f"No workspace found matching '{reference}'. Show available workspaces.",
                    "available": workspaces[:5],
                }
            )

    @kernel_function(
        name="normalize_test_reference",
        description="IMPORTANT: Convert user's natural language test reference to internal test group name. "
        "Users say 'database tests', 'HANA', 'central services', 'SCS' - this returns the internal group name. "
        "Call this BEFORE calling any test-related functions.",
    )
    def normalize_test_reference(
        self,
        user_input: Annotated[
            str, "What the user said about tests (e.g., 'database', 'HANA', 'central services')"
        ],
    ) -> Annotated[str, "JSON with internal test group name(s)"]:
        """Convert user's natural language to internal test group names."""
        user_input_lower = user_input.strip().lower()

        if user_input_lower in TEST_GROUP_ALIASES:
            group = TEST_GROUP_ALIASES[user_input_lower]
            if group == "ALL":
                return json.dumps(
                    {
                        "input": user_input,
                        "groups": ["HA_DB_HANA", "HA_SCS"],
                        "friendly_names": ["Database/HANA HA Tests", "Central Services HA Tests"],
                        "message": "Both database and central services test groups selected",
                    }
                )
            return json.dumps(
                {
                    "input": user_input,
                    "groups": [group],
                    "friendly_names": [TEST_GROUP_FRIENDLY_NAMES.get(group, group)],
                    "message": f"'{user_input}' maps to {TEST_GROUP_FRIENDLY_NAMES.get(group, group)}",
                }
            )

        matched_groups = set()
        for alias, group in TEST_GROUP_ALIASES.items():
            if alias in user_input_lower or user_input_lower in alias:
                if group != "ALL":
                    matched_groups.add(group)

        if matched_groups:
            groups = list(matched_groups)
            return json.dumps(
                {
                    "input": user_input,
                    "groups": groups,
                    "friendly_names": [TEST_GROUP_FRIENDLY_NAMES.get(g, g) for g in groups],
                    "message": f"Found {len(groups)} matching test group(s)",
                }
            )

        return json.dumps(
            {
                "input": user_input,
                "groups": [],
                "message": "Could not determine test group. Available options:",
                "available": {
                    "Database/HANA tests": "Say 'database', 'HANA', 'db', or 'hana failover'",
                    "Central Services tests": "Say 'central services', 'SCS', 'ASCS', or 'ERS'",
                    "All HA tests": "Say 'all', 'both', or 'everything'",
                },
            }
        )

    @kernel_function(
        name="lookup_abbreviation",
        description="Look up a project-specific abbreviation. Only use for uncommon terms "
        "like 'AFA', 'SBD'. For common terms like 'HANA' or 'Pacemaker', rely on your "
        "training knowledge instead.",
    )
    def lookup_abbreviation(
        self,
        term: Annotated[str, "The abbreviation to look up (e.g., 'AFA', 'SBD')"],
    ) -> Annotated[str, "Definition or 'not found'"]:
        """Look up a project-specific abbreviation."""
        term = term.strip().upper()

        if term in PROJECT_ABBREVIATIONS:
            return json.dumps(
                {
                    "term": term,
                    "definition": PROJECT_ABBREVIATIONS[term],
                }
            )

        return json.dumps(
            {
                "term": term,
                "found": False,
                "hint": "Use your knowledge or web_search for general SAP/Azure terms.",
            }
        )

    @kernel_function(
        name="get_workspace_naming_convention",
        description="Explain this project's workspace naming convention. Use when user asks "
        "how workspaces are named or when you need to parse a workspace ID.",
    )
    def get_workspace_naming_convention(self) -> Annotated[str, "Naming convention details"]:
        """Return the workspace naming convention for this project."""
        return json.dumps(
            {
                "format": "ENV-REGION-DEPLOYMENT-SID",
                "components": {
                    "ENV": "Environment: DEV, QA, or PROD",
                    "REGION": "Azure region code (4 letters): WEEU, EAUS, WEUS",
                    "DEPLOYMENT": "Deployment ID: SAP01, SAP02, etc.",
                    "SID": "SAP System ID: 3 alphanumeric chars",
                },
                "examples": [
                    "QA-WEEU-SAP01-X01",
                    "PROD-EAUS-SAP01-P01",
                    "DEV-WEUS-SAP02-D01",
                ],
                "location": "WORKSPACES/SYSTEM/{WORKSPACE_ID}/",
            }
        )
