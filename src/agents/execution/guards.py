# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Deterministic guard layer for safety-critical checks.

This module enforces safety constraints that must NEVER be bypassed
by LLM reasoning. All guards are:
- Deterministic (same input → same output)
- Fast (no LLM calls)
- Auditable (structured results)
- Fully tested (100% coverage target)

Guards handle:
- Workspace locking (one job per workspace)
- Environment gating (no destructive tests on PRD)
- Permission checks
- Input validation
"""

from typing import Callable, Optional, TYPE_CHECKING, Any

from semantic_kernel.filters.functions.function_invocation_context import (
    FunctionInvocationContext,
)
from semantic_kernel.functions.function_result import FunctionResult

from src.agents.constants import GUARDED_FUNCTIONS
from src.agents.observability import get_logger
from src.agents.models.execution import GuardReason, GuardResult

if TYPE_CHECKING:
    from src.agents.execution.store import JobStore
    from src.agents.models.job import ExecutionJob
    from src.agents.workspace.workspace_store import WorkspaceStore

logger = get_logger(__name__)


class GuardLayer:
    """Deterministic safety guard layer.

    This class enforces safety constraints before any action is executed.
    It does NOT use LLM reasoning - all checks are pure Python logic.
    """

    def __init__(
        self,
        job_store: Optional["JobStore"] = None,
        workspace_store: Optional["WorkspaceStore"] = None,
    ) -> None:
        """Initialize the guard layer.

        :param job_store: Job store for workspace locking checks
        :param workspace_store: Workspace store for environment checks
        """
        self.job_store = job_store
        self.workspace_store = workspace_store

    def check_execution(
        self,
        workspace_id: str,
        test_ids: list[str],
        is_destructive: bool = False,
    ) -> GuardResult:
        """Check if test execution is allowed.

        Validates:
        1. Workspace exists
        2. Workspace is not locked by another job
        3. Destructive tests not on PRD

        :param workspace_id: Target workspace
        :param test_ids: Tests to execute
        :param is_destructive: Whether tests are destructive
        :returns: Guard result
        """
        if not self.job_store:
            return GuardResult.deny(
                reason=GuardReason.ASYNC_NOT_ENABLED,
                message="Async execution not enabled. Job store not configured.",
            )

        if not self.workspace_store:
            return GuardResult.deny(
                reason=GuardReason.WORKSPACE_NOT_FOUND,
                message="Workspace store not configured.",
            )

        workspace = self.workspace_store.get_workspace(workspace_id)
        if not workspace:
            return GuardResult.deny(
                reason=GuardReason.WORKSPACE_NOT_FOUND,
                message=f"Workspace '{workspace_id}' not found.",
                details={"workspace_id": workspace_id},
            )

        active_job = self.job_store.get_active_job_for_workspace(workspace_id)
        if active_job:
            return GuardResult.deny(
                reason=GuardReason.WORKSPACE_LOCKED,
                message=(
                    f"Workspace '{workspace_id}' has an active job. "
                    f"Only one job per workspace is allowed."
                ),
                details={
                    "workspace_id": workspace_id,
                    "blocking_job_id": str(active_job.id),
                    "blocking_job_status": active_job.status.value,
                    "blocking_job_progress": active_job.progress_percent,
                    "blocking_job_step": active_job.current_step,
                },
                blocking_job=active_job,
            )

        if is_destructive and workspace.env == "PRD":
            return GuardResult.deny(
                reason=GuardReason.PRD_DESTRUCTIVE_BLOCKED,
                message=(
                    "Destructive tests are NEVER allowed on production environments. "
                    "This is a safety constraint that cannot be overridden."
                ),
                details={
                    "workspace_id": workspace_id,
                    "environment": workspace.env,
                    "test_ids": test_ids,
                },
            )

        if not test_ids:
            return GuardResult.deny(
                reason=GuardReason.INVALID_TEST_IDS,
                message="No test IDs provided.",
            )

        logger.info(
            f"Guard check PASSED for workspace={workspace_id}, "
            f"tests={len(test_ids)}, destructive={is_destructive}"
        )
        return GuardResult.allow()

    def check_cancel(self, job_id: str, user_id: Optional[str] = None) -> GuardResult:
        """Check if job cancellation is allowed.

        :param job_id: Job to cancel
        :param user_id: User requesting cancellation
        :returns: Guard result
        """
        if not self.job_store:
            return GuardResult.deny(
                reason=GuardReason.ASYNC_NOT_ENABLED,
                message="Job store not configured.",
            )

        job = self.job_store.get_job(job_id)
        if not job:
            return GuardResult.deny(
                reason=GuardReason.INVALID_TEST_IDS,
                message=f"Job '{job_id}' not found.",
                details={"job_id": job_id},
            )

        return GuardResult.allow()

    def format_denial_message(self, result: GuardResult) -> str:
        """Format a guard denial as a user-friendly message.

        This uses templates, not LLM, for consistent fast responses.

        :param result: Guard result to format
        :returns: Formatted message
        """
        if result.allowed:
            return ""

        if result.reason == GuardReason.WORKSPACE_LOCKED:
            job = result.blocking_job
            if job:
                started = (
                    job.started_at.strftime("%Y-%m-%d %H:%M:%S") if job.started_at else "pending"
                )
                return (
                    f"**Cannot start tests - workspace is busy**\n\n"
                    f"Workspace `{result.details.get('workspace_id')}` "
                    f"already has an active job:\n\n"
                    f"- **Job ID**: `{job.id}`\n"
                    f"- **Status**: {job.status.value}\n"
                    f"- **Started**: {started}\n"
                    f"- **Progress**: {job.progress_percent:.0f}%\n"
                    f"- **Current Step**: {job.current_step or 'initializing'}\n\n"
                    f"Please wait for the current job to complete, or cancel it:\n"
                    f'*"Cancel job {job.id}"*'
                )
            return f"**Workspace is busy**\n\n{result.message}"

        if result.reason == GuardReason.PRD_DESTRUCTIVE_BLOCKED:
            return (
                f"**Production Safety Block**\n\n"
                f"{result.message}\n\n"
                f"- **Workspace**: `{result.details.get('workspace_id')}`\n"
                f"- **Environment**: `{result.details.get('environment')}`\n\n"
                f"To run these tests, use a non-production workspace (DEV, QA, etc.)."
            )

        if result.reason == GuardReason.WORKSPACE_NOT_FOUND:
            return (
                f"**Workspace Not Found**\n\n"
                f"{result.message}\n\n"
                f'Use *"list workspaces"* to see available workspaces.'
            )

        if result.reason == GuardReason.ASYNC_NOT_ENABLED:
            return f"⚙️ **Configuration Error**\n\n{result.message}"

        if result.reason == GuardReason.INVALID_TEST_IDS:
            return f"**Invalid Request**\n\n{result.message}"

        return f"**Blocked**\n\n{result.message}"


class GuardFilter:
    """SK Filter that enforces GuardLayer checks before function execution.

    This filter intercepts calls to execution-related functions and
    validates them against the GuardLayer before allowing execution.
    """

    def __init__(self, guard_layer: GuardLayer) -> None:
        """Initialize GuardFilter.

        :param guard_layer: GuardLayer for safety checks
        """
        self.guard_layer = guard_layer

    async def on_function_invocation(
        self,
        context: FunctionInvocationContext,
        next: Callable[[FunctionInvocationContext], Any],
    ) -> None:
        """Filter function invocations for safety.

        :param context: Function invocation context
        :param next: Next handler in the filter chain
        """
        function_name = context.function.name
        plugin_name = context.function.plugin_name or ""

        if function_name not in GUARDED_FUNCTIONS:
            await next(context)
            return

        logger.info(f"GuardFilter checking: {plugin_name}.{function_name}")

        arguments = context.arguments
        workspace_id = arguments.get("workspace_id", "")
        test_ids = arguments.get("test_ids", [])
        if isinstance(test_ids, str):
            test_ids = [test_ids]
        test_id = arguments.get("test_id")
        if test_id and not test_ids:
            test_ids = [test_id]

        is_destructive = arguments.get("is_destructive", False)

        guard_result = self.guard_layer.check_execution(
            workspace_id=workspace_id,
            test_ids=test_ids if test_ids else ["unknown"],
            is_destructive=is_destructive,
        )

        if not guard_result.allowed:
            logger.warning(f"GuardFilter BLOCKED {function_name}: {guard_result.reason}")
            error_message = self.guard_layer.format_denial_message(guard_result)
            context.result = FunctionResult(
                function=context.function.metadata,
                value=error_message,
            )
            return

        logger.info(f"GuardFilter ALLOWED {function_name}")
        await next(context)
