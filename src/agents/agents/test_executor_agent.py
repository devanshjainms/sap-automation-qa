# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Test Executor Agent for SAP QA framework.

This agent executes tests from a TestPlan with strict safety controls:
- Environment gating (NEVER run destructive tests on PRD)
- Destructive test approval required
- Workspace validation
- Structured result collection
"""

import json
from typing import Optional
from datetime import datetime

from semantic_kernel import Kernel

from src.agents.models.chat import ChatMessage, ChatResponse
from src.agents.models.test import TestPlan
from src.agents.agents.base import Agent
from src.agents.workspace.workspace_store import WorkspaceStore
from src.agents.plugins.execution import ExecutionPlugin
from src.agents.models.execution import ExecutionRequest, ExecutionResult
from src.agents.models.reasoning import sanitize_snapshot
from src.agents.logging_config import get_logger

logger = get_logger(__name__)


class TestExecutorAgent(Agent):
    """Agent for executing SAP QA tests with strong safety and environment gating."""

    def __init__(
        self,
        kernel: Kernel,
        workspace_store: WorkspaceStore,
        execution_plugin: ExecutionPlugin,
    ):
        """Initialize TestExecutorAgent.

        :param kernel: Semantic Kernel instance
        :type kernel: Kernel
        :param workspace_store: WorkspaceStore for workspace metadata
        :type workspace_store: WorkspaceStore
        :param execution_plugin: ExecutionPlugin for test execution
        :type execution_plugin: ExecutionPlugin
        """
        super().__init__(
            name="test_executor",
            description="Executes SAP QA tests, runs playbooks, performs configuration checks, "
            + "and runs functional tests (HA, crash, failover) using Ansible. "
            + "Use this agent whenever the user asks to 'run', 'execute', 'perform', or 'start' a test.",
        )

        self.kernel = kernel
        self.workspace_store = workspace_store
        self.execution_plugin = execution_plugin

        logger.info("TestExecutorAgent initialized")

    async def execute(
        self, test_plan: TestPlan, request: ExecutionRequest
    ) -> list[ExecutionResult]:
        """Execute tests from a TestPlan based on ExecutionRequest.

        This method implements the core execution flow with safety controls:
        1. Validate workspace_id matches
        2. Determine effective environment
        3. Select tests to run based on mode
        4. Enforce environment + destructive gating
        5. Execute selected tests
        6. Collect and return results

        :param test_plan: TestPlan with safe and destructive tests
        :type test_plan: TestPlan
        :param request: ExecutionRequest specifying what to run
        :type request: ExecutionRequest
        :returns: List of ExecutionResult objects
        :rtype: list[ExecutionResult]
        """
        results = []
        if request.workspace_id != test_plan.workspace_id:
            logger.error(
                f"Workspace mismatch: request={request.workspace_id}, "
                f"plan={test_plan.workspace_id}"
            )
            raise ValueError(
                f"ExecutionRequest workspace_id '{request.workspace_id}' "
                f"does not match TestPlan workspace_id '{test_plan.workspace_id}'"
            )
        if request.env:
            effective_env = request.env
        else:
            parts = test_plan.workspace_id.split("-")
            if len(parts) >= 4:
                effective_env = parts[0]
            else:
                logger.warning(f"Cannot parse env from workspace_id: {test_plan.workspace_id}")
                effective_env = "UNKNOWN"

        logger.info(
            f"Executing tests for {test_plan.workspace_id} "
            f"(env={effective_env}, mode={request.mode})"
        )
        if effective_env == "PRD" and request.include_destructive:
            logger.error("Attempt to run destructive tests on PRD blocked")
            raise ValueError(
                "SAFETY VIOLATION: Destructive tests cannot be run on PRD environment. "
                "This operation has been blocked."
            )

        try:
            tests_to_execute = []

            if request.mode == "single":
                if request.tests_to_run and len(request.tests_to_run) > 0:
                    test_id = request.tests_to_run[0]
                    test = self._find_test_by_id(test_plan, test_id)
                    if test:
                        tests_to_execute.append(test)
                    else:
                        logger.warning(f"Test ID '{test_id}' not found in TestPlan")
                else:
                    logger.warning("No tests specified in ExecutionRequest")

            elif request.mode == "all_safe":
                tests_to_execute = list(test_plan.safe_tests)
                logger.info(f"Selected all {len(tests_to_execute)} safe tests")

            elif request.mode == "selected":
                if request.tests_to_run:
                    for test_id in request.tests_to_run:
                        test = next((t for t in test_plan.safe_tests if t.test_id == test_id), None)
                        if test:
                            tests_to_execute.append(test)
                        elif request.include_destructive:
                            test = next(
                                (t for t in test_plan.destructive_tests if t.test_id == test_id),
                                None,
                            )
                            if test:
                                if effective_env != "PRD":
                                    tests_to_execute.append(test)
                                    logger.warning(
                                        f"Including destructive test '{test_id}' "
                                        f"(env={effective_env})"
                                    )
                                else:
                                    logger.error(f"Blocked destructive test '{test_id}' on PRD")

                        if test is None:
                            logger.warning(f"Test ID '{test_id}' not found in TestPlan")
                else:
                    logger.warning("No tests specified for selected mode")

            if not tests_to_execute:
                logger.warning("No tests selected for execution")
                return results

            logger.info(f"Will execute {len(tests_to_execute)} tests")
            
            self.tracer.step(
                "test_selection",
                "decision",
                f"Selected {len(tests_to_execute)} tests for execution",
                output_snapshot=sanitize_snapshot({
                    "mode": request.mode,
                    "test_count": len(tests_to_execute),
                    "include_destructive": request.include_destructive,
                    "environment": effective_env
                })
            )

            for test in tests_to_execute:
                logger.info(
                    f"Executing test: {test.test_id} ({test.test_name}) "
                    f"[destructive={test.destructive}]"
                )
                result_json = self.execution_plugin.run_test_by_id(
                    workspace_id=test_plan.workspace_id, test_id=test.test_id
                )
                result_dict = json.loads(result_json)
                if "error" in result_dict:
                    logger.error(f"Test execution error: {result_dict['error']}")

                    exec_result = ExecutionResult(
                        test_id=test.test_id,
                        test_group=test.test_group,
                        workspace_id=test_plan.workspace_id,
                        env=effective_env,
                        action_type="test",
                        status="failed",
                        started_at=datetime.utcnow(),
                        finished_at=datetime.utcnow(),
                        hosts=[],
                        error_message=result_dict["error"],
                        details=result_dict,
                    )
                else:
                    exec_result = ExecutionResult(**result_dict)
                results.append(exec_result)
                logger.info(f"Test {test.test_id} completed with status: {exec_result.status}")
            return results

        except Exception as e:
            logger.error(f"Error in TestExecutorAgent: {e}", exc_info=True)

            error_result = ExecutionResult(
                workspace_id=request.workspace_id,
                action_type="test",
                status="failed",
                started_at=datetime.utcnow(),
                finished_at=datetime.utcnow(),
                hosts=[],
                error_message=str(e),
                details={"exception": str(e)},
            )
            return [error_result]

    def _find_test_by_id(self, test_plan: TestPlan, test_id: str):
        """Find a test by ID in the TestPlan.

        :param test_plan: TestPlan to search
        :type test_plan: TestPlan
        :param test_id: Test ID to find
        :type test_id: str
        :returns: PlannedTest or None
        :rtype: PlannedTest or None
        """
        test = next((t for t in test_plan.safe_tests if t.test_id == test_id), None)
        if test:
            return test

        test = next((t for t in test_plan.destructive_tests if t.test_id == test_id), None)
        return test

    def build_summary(self, results: list[ExecutionResult]) -> str:
        """Build human-readable summary from ExecutionResults.

        :param results: List of ExecutionResult objects
        :type results: list[ExecutionResult]
        :returns: Formatted summary string
        :rtype: str
        """
        if not results:
            return "No tests were executed."

        summary_lines = []
        summary_lines.append(f"# Execution Summary ({len(results)} test(s))\n")

        success_count = sum(1 for r in results if r.status == "success")
        failed_count = sum(1 for r in results if r.status == "failed")
        partial_count = sum(1 for r in results if r.status == "partial")
        skipped_count = sum(1 for r in results if r.status == "skipped")

        summary_lines.append(
            f"**Overall**: {success_count} succeeded, {failed_count} failed, "
            f"{partial_count} partial, {skipped_count} skipped\n"
        )

        for i, result in enumerate(results, 1):
            status_emoji = {"success": "✅", "failed": "❌", "partial": "⚠️", "skipped": "⏭️"}.get(
                result.status, "❓"
            )

            summary_lines.append(f"\n## {i}. {status_emoji} {result.test_id or 'Unknown Test'}")

            if result.test_group:
                summary_lines.append(f"   - **Group**: {result.test_group}")

            summary_lines.append(f"   - **Status**: {result.status}")
            summary_lines.append(f"   - **Workspace**: {result.workspace_id}")

            if result.env:
                summary_lines.append(f"   - **Environment**: {result.env}")

            if result.hosts:
                summary_lines.append(f"   - **Hosts**: {', '.join(result.hosts)}")

            if result.error_message:
                summary_lines.append(f"   - **Error**: {result.error_message}")

            duration = None
            if result.finished_at and result.started_at:
                duration = (result.finished_at - result.started_at).total_seconds()
                summary_lines.append(f"   - **Duration**: {duration:.1f}s")

        return "\n".join(summary_lines)

    async def run(
        self,
        messages: list[ChatMessage],
        context: Optional[dict] = None,
    ) -> ChatResponse:
        """Handle structured execution requests (Agent interface implementation).

        This agent expects structured input from the orchestrator:
        - context["test_plan"]: TestPlan object as dict
        - context["execution_request"]: ExecutionRequest object as dict

        :param messages: Chat messages (used for logging/context)
        :type messages: list[ChatMessage]
        :param context: Required context with test_plan and execution_request
        :type context: Optional[dict]
        :returns: ChatResponse with execution summary
        :rtype: ChatResponse
        """
        self.tracer.start()
        try:
            self.tracer.step(
                "execution_planning",
                "inference",
                "Understanding test execution request",
                input_snapshot=sanitize_snapshot({
                    "has_test_plan": context and "test_plan" in context if context else False,
                    "has_execution_request": context and "execution_request" in context if context else False,
                    "message_count": len(messages)
                })
            )
            
            if not context or "test_plan" not in context or "execution_request" not in context:
                raise ValueError(
                    "TestExecutorAgent requires structured input with test_plan and execution_request"
                )
            test_plan_dict = context["test_plan"]
            execution_request_dict = context["execution_request"]
            test_plan = TestPlan(**test_plan_dict)
            execution_request = ExecutionRequest(**execution_request_dict)

            logger.info(f"Executing test plan for workspace {test_plan.workspace_id}")
            results = await self.execute(test_plan, execution_request)
            self.tracer.step(
                "execution_run",
                "tool_call",
                "Test execution completed",
                output_snapshot=sanitize_snapshot({
                    "total_results": len(results),
                    "passed": sum(1 for r in results if r.status == "passed"),
                    "failed": sum(1 for r in results if r.status == "failed"),
                    "skipped": sum(1 for r in results if r.status == "skipped")
                })
            )
            
            summary = self.build_summary(results)

            return ChatResponse(
                messages=[ChatMessage(role="assistant", content=summary)],
                reasoning_trace=self.tracer.get_trace()
            )

        except Exception as e:
            logger.error(f"Error in TestExecutorAgent.run: {e}")
            
            self.tracer.step(
                "execution_run",
                "inference",
                f"Error during test execution: {str(e)}",
                error=str(e),
                output_snapshot=sanitize_snapshot({"error_type": type(e).__name__})
            )
            
            raise
        
        finally:
            self.tracer.finish()
