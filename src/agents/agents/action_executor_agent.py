# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Action Executor Agent for SAP QA framework.

This agent executes actions from an ActionPlan with strict safety controls:
- Environment gating (NEVER run destructive tests on PRD)
- Destructive test approval required
- Workspace validation
- Structured result collection
- Async execution with real-time status updates
"""

import json
from typing import Optional, TYPE_CHECKING
from datetime import datetime

from semantic_kernel import Kernel
from semantic_kernel.filters import FilterTypes

from src.agents.models.chat import ChatMessage, ChatResponse
from src.agents.models.test import TestPlan
from src.agents.models.action import ActionPlan
from src.agents.agents.base import Agent
from src.agents.workspace.workspace_store import WorkspaceStore
from src.agents.plugins.execution import ExecutionPlugin
from src.agents.plugins.workspace import WorkspacePlugin
from src.agents.plugins.ssh import SSHPlugin
from src.agents.models.execution import ExecutionRequest, ExecutionResult
from src.agents.models.reasoning import sanitize_snapshot
from src.agents.execution import GuardLayer, GuardFilter
from src.agents.observability import get_logger

if TYPE_CHECKING:
    from src.agents.execution import JobStore, JobWorker, ExecutionJob

logger = get_logger(__name__)


class ActionExecutorAgent(Agent):
    """Agent for executing SAP QA actions with strong safety and environment gating.

    Uses Semantic Kernel with:
    - ExecutionPlugin: Provides test execution tools as SK functions
    - GuardFilter: Intercepts function calls to enforce safety constraints

    Supports two execution modes:
    1. Synchronous (blocking): For quick tests or when streaming not needed
    2. Asynchronous (non-blocking): For long-running tests with real-time updates
    """

    def __init__(
        self,
        kernel: Kernel,
        workspace_store: WorkspaceStore,
        execution_plugin: ExecutionPlugin,
        job_store: Optional["JobStore"] = None,
        job_worker: Optional["JobWorker"] = None,
    ):
        """Initialize ActionExecutorAgent.

        Registers ExecutionPlugin with Semantic Kernel and adds GuardFilter
        for safety enforcement.

        :param kernel: Semantic Kernel instance
        :type kernel: Kernel
        :param workspace_store: WorkspaceStore for workspace metadata
        :type workspace_store: WorkspaceStore
        :param execution_plugin: ExecutionPlugin for test execution
        :type execution_plugin: ExecutionPlugin
        :param job_store: Optional JobStore for async execution tracking
        :type job_store: Optional[JobStore]
        :param job_worker: Optional JobWorker for background execution
        :type job_worker: Optional[JobWorker]
        """
        super().__init__(
            name="action_executor",
            description="Executes SAP QA actions, runs playbooks, performs configuration checks, "
            + "and runs functional tests (HA, crash, failover) using Ansible. "
            + "Use this agent whenever the user asks to 'run', 'execute', 'perform', or 'start' a test or action.",
        )

        self.kernel = kernel
        self.workspace_store = workspace_store
        self.execution_plugin = execution_plugin
        self.job_store = job_store
        self.job_worker = job_worker
        self._async_enabled = job_store is not None and job_worker is not None

        self.guard_layer = GuardLayer(
            job_store=job_store,
            workspace_store=workspace_store,
        )

        self._safe_add_plugin(execution_plugin, "execution")
        self._safe_add_plugin(WorkspacePlugin(workspace_store), "workspace")
        self._safe_add_plugin(SSHPlugin(), "ssh")
        if getattr(execution_plugin, "keyvault_plugin", None) is not None:
            self._safe_add_plugin(execution_plugin.keyvault_plugin, "keyvault")

        guard_filter = GuardFilter(self.guard_layer)
        self.kernel.add_filter(
            filter_type=FilterTypes.FUNCTION_INVOCATION,
            filter=guard_filter.on_function_invocation,
        )

        logger.info(
            f"ActionExecutorAgent initialized with SK plugin and guard filter "
            f"(async_enabled={self._async_enabled})"
        )

    def _safe_add_plugin(self, plugin: object, plugin_name: str) -> None:
        """Add an SK plugin if not already present.

        Semantic Kernel plugin registration can vary depending on how the runtime
        constructs kernels/agents. This keeps agent capabilities consistent.
        """
        try:
            self.kernel.add_plugin(
                plugin=plugin,
                plugin_name=plugin_name,
            )
        except Exception as e:
            logger.info(f"Plugin '{plugin_name}' already registered or unavailable: {e}")

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
                output_snapshot=sanitize_snapshot(
                    {
                        "mode": request.mode,
                        "test_count": len(tests_to_execute),
                        "include_destructive": request.include_destructive,
                        "environment": effective_env,
                    }
                ),
            )

            for test in tests_to_execute:
                logger.info(
                    f"Executing test: {test.test_id} ({test.test_name}) "
                    f"[destructive={test.destructive}]"
                )

                result = await self.kernel.invoke(
                    plugin_name="execution",
                    function_name="run_test_by_id",
                    workspace_id=test_plan.workspace_id,
                    test_id=test.test_id,
                    test_group=test.test_group,
                )

                result_json = str(result) if result else "{}"
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
            logger.error(f"Error in ActionExecutorAgent: {e}", exc_info=e)

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

    async def execute_async(
        self,
        workspace_id: str,
        test_ids: list[str],
        test_group: str,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> "ExecutionJob":
        """Start async test execution and return job for tracking.

        This method creates a job and starts execution in the background.
        The caller can then stream job events for real-time updates.

        :param workspace_id: Workspace to run tests against
        :type workspace_id: str
        :param test_ids: List of test IDs to execute
        :type test_ids: list[str]
        :param test_group: Test group (HA_DB_HANA, HA_SCS, etc.)
        :type test_group: str
        :param conversation_id: Associated conversation ID
        :type conversation_id: Optional[str]
        :param user_id: User who initiated execution
        :type user_id: Optional[str]
        :returns: ExecutionJob for tracking
        :rtype: ExecutionJob
        :raises RuntimeError: If async execution not enabled
        """
        guard_result = self.guard_layer.check_execution(
            workspace_id=workspace_id,
            test_ids=test_ids,
            is_destructive=False,
        )
        if not guard_result.allowed:
            raise RuntimeError(self.guard_layer.format_denial_message(guard_result))

        assert self.job_store is not None
        assert self.job_worker is not None

        workspace = self.workspace_store.get_workspace(workspace_id)
        assert workspace is not None
        job = self.job_store.create_job(
            workspace_id=workspace_id,
            test_ids=test_ids,
            conversation_id=conversation_id,
            user_id=user_id,
            test_id=test_ids[0] if len(test_ids) == 1 else None,
            test_group=test_group,
            metadata={
                "environment": workspace.env,
                "initiated_via": "chat",
            },
        )

        logger.info(
            f"Created async job {job.id} for {len(test_ids)} tests " f"on workspace {workspace_id}"
        )
        await self.job_worker.submit_job(job)
        return job

    def get_active_job_for_workspace(self, workspace_id: str) -> Optional["ExecutionJob"]:
        """Get the active job for a workspace, if any.

        :param workspace_id: Workspace ID to check
        :type workspace_id: str
        :returns: Active job or None
        :rtype: Optional[ExecutionJob]
        """
        if not self.job_store:
            return None
        return self.job_store.get_active_job_for_workspace(workspace_id)

    def get_job_status(self, job_id: str) -> Optional["ExecutionJob"]:
        """Get status of a running or completed job.

        :param job_id: Job ID to check
        :type job_id: str
        :returns: Job if found
        :rtype: Optional[ExecutionJob]
        """
        if not self.job_store:
            return None
        return self.job_store.get_job(job_id)

    def get_active_jobs_for_user(self, user_id: str) -> list["ExecutionJob"]:
        """Get active jobs for a user.

        :param user_id: User ID
        :type user_id: str
        :returns: List of active jobs
        :rtype: list[ExecutionJob]
        """
        if not self.job_store:
            return []
        return self.job_store.get_active_jobs(user_id)

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

            summary_lines.append(f"\n## {i}. {result.test_id or 'Unknown Test'}")

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

        This agent supports two modes:
        1. Synchronous: Uses context["test_plan"] and context["execution_request"]
        2. Async (preferred): Uses context["async_execution"] with workspace_id, test_ids, test_group

        :param messages: Chat messages (used for logging/context)
        :type messages: list[ChatMessage]
        :param context: Context with execution parameters
        :type context: Optional[dict]
        :returns: ChatResponse with execution summary or job info
        :rtype: ChatResponse
        """
        self.tracer.start()
        try:
            context = context or {}
            if "async_execution" in context and self._async_enabled:
                return await self._run_async(messages, context)
            if "job_status_query" in context:
                return await self._handle_job_status_query(context)
            self.tracer.step(
                "execution_planning",
                "inference",
                "Understanding test execution request",
                input_snapshot=sanitize_snapshot(
                    {
                        "has_test_plan": "test_plan" in context,
                        "has_execution_request": "execution_request" in context,
                        "message_count": len(messages),
                    }
                ),
            )

            if "action_plan" in context:
                return await self._run_action_plan(messages, context)

            if "test_plan" not in context or "execution_request" not in context:
                raise ValueError(
                    "ActionExecutorAgent requires structured input with either action_plan, "
                    "or test_plan + execution_request"
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
                output_snapshot=sanitize_snapshot(
                    {
                        "total_results": len(results),
                        "passed": sum(1 for r in results if r.status == "passed"),
                        "failed": sum(1 for r in results if r.status == "failed"),
                        "skipped": sum(1 for r in results if r.status == "skipped"),
                    }
                ),
            )

            summary = self.build_summary(results)

            return ChatResponse(
                messages=[ChatMessage(role="assistant", content=summary)],
                reasoning_trace=self.tracer.get_trace(),
                metadata=None,
            )

        except Exception as e:
            logger.error(f"Error in ActionExecutorAgent.run: {e}")

            self.tracer.step(
                "execution_run",
                "inference",
                f"Error during test execution: {str(e)}",
                error=str(e),
                output_snapshot=sanitize_snapshot({"error_type": type(e).__name__}),
            )

            raise

        finally:
            self.tracer.finish()

    def _validate_action_plan_execution(self, plan: ActionPlan) -> None:
        """Deterministic validation before executing an ActionPlan."""

        workspace = self.workspace_store.get_workspace(plan.workspace_id)
        if not workspace:
            raise ValueError(f"Workspace '{plan.workspace_id}' not found")

        allowed_plugins = {"ssh", "execution", "workspace", "keyvault"}
        for job in plan.jobs:
            if job.plugin_name not in allowed_plugins:
                raise ValueError(
                    f"ActionPlan job '{job.job_id}' uses disallowed plugin '{job.plugin_name}'"
                )

        if any(job.destructive for job in plan.jobs) and workspace.env == "PRD":
            raise ValueError(
                "SAFETY VIOLATION: Destructive jobs cannot be executed on PRD environment."
            )

    async def _run_action_plan(
        self,
        messages: list[ChatMessage],
        context: dict,
    ) -> ChatResponse:
        """Execute a unified ActionPlan as a sequence of tool invocations."""

        _ = messages

        action_plan_dict = context.get("action_plan")
        if not isinstance(action_plan_dict, dict):
            raise ValueError("action_plan must be a dict")

        plan = ActionPlan(**action_plan_dict)
        self._validate_action_plan_execution(plan)

        self.tracer.step(
            "execution_planning",
            "decision",
            "Executing ActionPlan",
            output_snapshot=sanitize_snapshot(
                {
                    "workspace_id": plan.workspace_id,
                    "intent": plan.intent,
                    "job_count": len(plan.jobs),
                }
            ),
        )

        results: list[dict] = []
        for job in plan.jobs:
            try:
                self.tracer.step(
                    "execution_run",
                    "tool_call",
                    f"Invoking {job.plugin_name}.{job.function_name}",
                    input_snapshot=sanitize_snapshot({"job_id": job.job_id, "args": job.arguments}),
                )

                result = await self.kernel.invoke(
                    plugin_name=job.plugin_name,
                    function_name=job.function_name,
                    **(job.arguments or {}),
                )

                result_text = str(result) if result is not None else "{}"
                try:
                    result_payload = json.loads(result_text)
                except json.JSONDecodeError:
                    result_payload = {"raw": result_text}

                results.append(
                    {
                        "job_id": job.job_id,
                        "title": job.title,
                        "plugin_name": job.plugin_name,
                        "function_name": job.function_name,
                        "success": True,
                        "result": result_payload,
                    }
                )
            except Exception as e:
                logger.error(f"ActionPlan job failed: job_id={job.job_id} error={e}")
                results.append(
                    {
                        "job_id": job.job_id,
                        "title": job.title,
                        "plugin_name": job.plugin_name,
                        "function_name": job.function_name,
                        "success": False,
                        "error": str(e),
                    }
                )

        ok = sum(1 for r in results if r.get("success"))
        total = len(results)
        summary_lines = [
            f"ActionPlan execution for {plan.workspace_id} ({plan.intent})",
            f"Completed {ok}/{total} jobs",
        ]
        for r in results:
            status = "OK" if r.get("success") else "FAILED"
            summary_lines.append(f"- {status}: {r.get('title') or r.get('job_id')}")

        return ChatResponse(
            messages=[ChatMessage(role="assistant", content="\n".join(summary_lines))],
            action_plan=plan.model_dump(),
            reasoning_trace=self.tracer.get_trace(),
            metadata={"job_results": results},
        )

    async def _run_async(
        self,
        messages: list[ChatMessage],
        context: dict,
    ) -> ChatResponse:
        """Handle async execution request.

        :param messages: Chat messages
        :type messages: list[ChatMessage]
        :param context: Context with async_execution params
        :type context: dict
        :returns: ChatResponse with job info
        :rtype: ChatResponse
        """
        async_params = context["async_execution"]
        workspace_id = async_params["workspace_id"]
        test_ids = async_params.get("test_ids", [])
        test_group = async_params.get("test_group", "CONFIG_CHECKS")
        conversation_id = context.get("conversation_id")
        user_id = context.get("user_id")

        self.tracer.step(
            "execution_async",
            "tool_call",
            f"Starting async execution for {len(test_ids)} tests",
            input_snapshot=sanitize_snapshot(
                {
                    "workspace_id": workspace_id,
                    "test_count": len(test_ids),
                    "test_group": test_group,
                }
            ),
        )

        try:
            job = await self.execute_async(
                workspace_id=workspace_id,
                test_ids=test_ids,
                test_group=test_group,
                conversation_id=conversation_id,
                user_id=user_id,
            )

            test_list = ", ".join(test_ids[:3])
            if len(test_ids) > 3:
                test_list += f" and {len(test_ids) - 3} more"

            response_content = (
                f"**Starting test execution**\n\n"
                f"- **Workspace**: `{workspace_id}`\n"
                f"- **Tests**: {test_list}\n"
                f"- **Job ID**: `{job.id}`\n\n"
                f"I'll provide real-time updates as the tests progress..."
            )

            self.tracer.step(
                "execution_async",
                "decision",
                f"Job {job.id} submitted for execution",
                output_snapshot=sanitize_snapshot(
                    {
                        "job_id": str(job.id),
                        "status": job.status.value,
                    }
                ),
            )

            return ChatResponse(
                messages=[ChatMessage(role="assistant", content=response_content)],
                reasoning_trace=self.tracer.get_trace(),
                metadata={"job_id": str(job.id), "streaming": True},
            )

        except Exception as e:
            logger.error(f"Failed to start async execution: {e}")
            return ChatResponse(
                messages=[ChatMessage(role="assistant", content=str(e))],
                reasoning_trace=self.tracer.get_trace(),
                metadata=None,
            )

    async def _handle_job_status_query(self, context: dict) -> ChatResponse:
        """Handle job status query.

        :param context: Context with job_status_query params
        :type context: dict
        :returns: ChatResponse with job status
        :rtype: ChatResponse
        """
        query = context["job_status_query"]
        job_id = query.get("job_id")
        user_id = query.get("user_id")

        if job_id:
            job = self.get_job_status(job_id)
            if job:
                from src.agents.execution.worker import JobEventEmitter

                summary = JobEventEmitter.format_job_summary(job)
                return ChatResponse(
                    messages=[ChatMessage(role="assistant", content=summary)],
                    reasoning_trace=self.tracer.get_trace(),
                    metadata=None,
                )
            else:
                return ChatResponse(
                    messages=[ChatMessage(role="assistant", content=f"Job `{job_id}` not found.")],
                    reasoning_trace=self.tracer.get_trace(),
                    metadata=None,
                )
        elif user_id:
            jobs = self.get_active_jobs_for_user(user_id)
            if jobs:
                from src.agents.execution.worker import JobEventEmitter

                lines = ["**Your Active Jobs:**\n"]
                for job in jobs:
                    lines.append(JobEventEmitter.format_job_summary(job))
                    lines.append("")
                return ChatResponse(
                    messages=[ChatMessage(role="assistant", content="\n".join(lines))],
                    reasoning_trace=self.tracer.get_trace(),
                    metadata=None,
                )
            else:
                return ChatResponse(
                    messages=[
                        ChatMessage(role="assistant", content="You have no active test executions.")
                    ],
                    reasoning_trace=self.tracer.get_trace(),
                    metadata=None,
                )
        else:
            return ChatResponse(
                messages=[
                    ChatMessage(
                        role="assistant",
                        content="Please specify a job ID or ask about your active jobs.",
                    )
                ],
                reasoning_trace=self.tracer.get_trace(),
                metadata=None,
            )
