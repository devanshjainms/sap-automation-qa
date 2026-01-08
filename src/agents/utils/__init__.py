# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Utility modules for SAP QA agent framework.

This package contains infrastructure utilities that are NOT agent methods.
They are called by the orchestrator/API layer for post-processing, not
by agents during LLM reasoning.

Design Philosophy:
- Agents are pure AI agents with only @kernel_function tools
- Utilities handle validation, normalization, and infrastructure concerns
- This separation ensures agents don't bypass LLM autonomy
"""

from src.agents.utils.action_plan_utils import normalize_action_plan

__all__ = [
    "normalize_action_plan",
]
