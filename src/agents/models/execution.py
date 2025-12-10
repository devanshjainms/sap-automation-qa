# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Pydantic models for SAP QA test execution.

This module defines the contract between the TestPlannerAgent and TestExecutorAgent,
ensuring type-safe, auditable test execution with proper environment gating.
"""

from dataclasses import dataclass, field
from enum import Enum
from pydantic import BaseModel, Field
from typing import Any, Literal, Optional, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from src.agents.models.job import ExecutionJob


class GuardReason(Enum):
    """Enumeration of guard rejection reasons.

    These are deterministic, auditable reasons why a guard check failed.
    """

    WORKSPACE_LOCKED = "workspace_locked"
    PRD_DESTRUCTIVE_BLOCKED = "prd_destructive_blocked"
    WORKSPACE_NOT_FOUND = "workspace_not_found"
    INVALID_TEST_IDS = "invalid_test_ids"
    PERMISSION_DENIED = "permission_denied"
    ASYNC_NOT_ENABLED = "async_not_enabled"


@dataclass
class GuardResult:
    """Result of a guard check.

    :param allowed: Whether the action is allowed
    :param reason: Rejection reason if not allowed
    :param message: Human-readable message
    :param details: Additional context for the rejection
    :param blocking_job: Job that's blocking (for workspace lock)
    """

    allowed: bool
    reason: Optional[GuardReason] = None
    message: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)
    blocking_job: Optional["ExecutionJob"] = None

    @staticmethod
    def allow() -> "GuardResult":
        """Create an allowing result."""
        return GuardResult(allowed=True)

    @staticmethod
    def deny(
        reason: GuardReason,
        message: str,
        details: Optional[dict[str, Any]] = None,
        blocking_job: Optional["ExecutionJob"] = None,
    ) -> "GuardResult":
        """Create a denying result."""
        return GuardResult(
            allowed=False,
            reason=reason,
            message=message,
            details=details or {},
            blocking_job=blocking_job,
        )


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
