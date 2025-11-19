# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Pydantic models for SAP QA test execution.

This module defines the contract between the TestPlannerAgent and TestExecutorAgent,
ensuring type-safe, auditable test execution with proper environment gating.
"""

from pydantic import BaseModel, Field
from typing import Any, Literal, Optional
from datetime import datetime


class ExecutionResult(BaseModel):
    """Result of a test execution or diagnostic command.

    This model captures all execution metadata for auditing and reporting.
    """

    test_id: Optional[str] = Field(
        default=None, description="PlannedTest.test_id or combined_id from TestPlan"
    )

    test_group: Optional[str] = Field(
        default=None, description="Test group (HA_DB_HANA, HA_SCS, etc.)"
    )

    combined_id: Optional[str] = Field(
        default=None, description="Combined identifier if applicable"
    )

    workspace_id: str = Field(
        description="Workspace where the action was executed (e.g., DEV-WEEU-SAP01-X00)"
    )

    env: Optional[str] = Field(default=None, description="Environment (DEV, QA, PRD)")

    action_type: Literal["test", "config_check", "command", "log"] = Field(
        description="Type of action executed"
    )

    status: Literal["success", "failed", "partial", "skipped"] = Field(
        description="Execution status"
    )

    started_at: datetime = Field(description="When the execution started")

    finished_at: Optional[datetime] = Field(default=None, description="When the execution finished")

    hosts: list[str] = Field(
        default_factory=list, description="List of hosts touched by this action"
    )

    stdout: Optional[str] = Field(default=None, description="Summarized stdout from execution")

    stderr: Optional[str] = Field(default=None, description="Summarized stderr from execution")

    error_message: Optional[str] = Field(default=None, description="High-level error summary")

    details: dict[str, Any] = Field(
        default_factory=dict, description="Raw per-host results, exit codes, ansible facts, etc."
    )


class ExecutionRequest(BaseModel):
    """Request to execute tests from a TestPlan.

    This model controls which tests run and enforces safety constraints.
    """

    workspace_id: str = Field(description="Target workspace identifier")

    env: Optional[str] = Field(
        default=None, description="Optional environment override (use with caution)"
    )

    tests_to_run: Optional[list[str]] = Field(
        default=None, description="List of test_ids or combined_ids to execute"
    )

    include_destructive: bool = Field(
        default=False,
        description="Must be True to execute destructive tests (still subject to env gating)",
    )

    mode: Literal["single", "all_safe", "selected"] = Field(
        default="single",
        description="Execution mode: single test, all safe tests, or selected tests",
    )
