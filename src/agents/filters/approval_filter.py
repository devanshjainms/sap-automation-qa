# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Kernel-level approval filter for execution safety.

This filter blocks hallucinated or invalid execution requests before any
Ansible or SSH action is invoked.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import yaml
from semantic_kernel.filters.functions.function_invocation_context import (
    FunctionInvocationContext,
)
from semantic_kernel.functions.function_result import FunctionResult

from src.agents.constants import TEST_GROUP_PLAYBOOKS
from src.agents.observability import get_logger
from src.agents.plugins.command_validator import validate_readonly_command
from src.agents.workspace.workspace_store import WorkspaceStore

logger = get_logger(__name__)


class ApprovalFilter:
    """Kernel filter that validates execution requests before tool invocation."""

    def __init__(self, test_catalog_path: str = "src/vars/input-api.yaml") -> None:
        self.test_catalog_path = Path(test_catalog_path)
        self.test_catalog = self._load_test_catalog()
        workspace_root = Path(__file__).resolve().parents[3] / "WORKSPACES" / "SYSTEM"
        self.workspace_store = WorkspaceStore(workspace_root)

    def _load_test_catalog(self) -> dict[str, dict[str, dict[str, bool]]]:
        if not self.test_catalog_path.exists():
            logger.warning(
                f"Test catalog not found at {self.test_catalog_path}. "
                "Execution approvals will be limited to known playbook groups."
            )
            return {}

        try:
            with open(self.test_catalog_path, "r") as handle:
                config = yaml.safe_load(handle) or {}
        except Exception as exc:
            logger.warning(f"Failed to load test catalog: {exc}")
            return {}

        catalog: dict[str, dict[str, dict[str, bool]]] = {}
        for group in config.get("test_groups", []):
            group_name = group.get("name")
            if not group_name:
                continue
            tests = {}
            for test_case in group.get("test_cases", []):
                task_name = test_case.get("task_name")
                if not task_name or not test_case.get("enabled", False):
                    continue
                tests[task_name] = {
                    "destructive": bool(test_case.get("destructive", False)),
                }
            if tests:
                catalog[group_name] = tests
        return catalog

    async def on_function_invocation(
        self,
        context: FunctionInvocationContext,
        next: Callable[[FunctionInvocationContext], Any],
    ) -> None:
        """Validate execution-related tool calls before invocation."""
        function_name = context.function.name
        plugin_name = context.function.plugin_name or ""

        if plugin_name != "execution":
            await next(context)
            return

        if function_name == "run_readonly_command":
            command = str(context.arguments.get("command", ""))
            try:
                validate_readonly_command(command)
            except ValueError as exc:
                logger.warning(f"ApprovalFilter blocked command: {exc}")
                context.result = FunctionResult(
                    function=context.function.metadata,
                    value=f"Command rejected by approval filter: {exc}",
                )
                return

        if function_name == "run_test_by_id":
            test_group = str(context.arguments.get("test_group", "")).strip()
            test_id = str(context.arguments.get("test_id", "")).strip()

            if not test_group or test_group not in TEST_GROUP_PLAYBOOKS:
                context.result = FunctionResult(
                    function=context.function.metadata,
                    value=(
                        f"Test group '{test_group}' is not recognized. "
                        f"Valid groups: {', '.join(sorted(TEST_GROUP_PLAYBOOKS.keys()))}."
                    ),
                )
                return

            allowed_tests = self.test_catalog.get(test_group)
            if allowed_tests is not None and test_id not in allowed_tests:
                context.result = FunctionResult(
                    function=context.function.metadata,
                    value=(
                        f"Test ID '{test_id}' is not approved for group '{test_group}'. "
                        "Select a test from the configured catalog."
                    ),
                )
                return

            if allowed_tests is not None:
                workspace_id = str(context.arguments.get("workspace_id", "")).strip()
                workspace = (
                    self.workspace_store.get_workspace(workspace_id) if workspace_id else None
                )
                if workspace and allowed_tests.get(test_id, {}).get("destructive") and workspace.env == "PRD":
                    context.result = FunctionResult(
                        function=context.function.metadata,
                        value=(
                            "Destructive tests are not allowed on production workspaces. "
                            "Choose a non-production workspace for destructive runs."
                        ),
                    )
                    return

        await next(context)
