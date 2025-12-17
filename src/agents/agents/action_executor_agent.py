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
from typing import Any, Optional, TYPE_CHECKING

from semantic_kernel import Kernel
from semantic_kernel.contents import ChatHistory
from semantic_kernel.filters import FilterTypes

from src.agents.models.chat import ChatMessage, ChatResponse
from src.agents.agents.base import Agent
from src.agents.workspace.workspace_store import WorkspaceStore
from src.agents.plugins.execution import ExecutionPlugin
from src.agents.plugins.workspace import WorkspacePlugin
from src.agents.plugins.ssh import SSHPlugin
from src.agents.models.reasoning import sanitize_snapshot
from src.agents.execution import GuardLayer, GuardFilter
from src.agents.observability import get_logger
from src.agents.prompts import ACTION_EXECUTOR_SYSTEM_PROMPT

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

    async def _run_agentic(self, messages: list[ChatMessage], context: dict) -> ChatResponse:
        """Run an agentic LLM+tools loop.

        The LLM decides which tools to call (execution/workspace/ssh/keyvault), guarded by
        GuardFilter. The assistant message is the final synthesized answer.
        """

        self.tracer.step(
            "execution_planning",
            "inference",
            "Running agentic tool loop",
            input_snapshot=sanitize_snapshot(
                {
                    "message_count": len(messages),
                    "has_agent_input": "agent_input" in context,
                }
            ),
        )

        chat_history = ChatHistory()
        chat_history.add_system_message(ACTION_EXECUTOR_SYSTEM_PROMPT)

        agent_input = context.get("agent_input") if isinstance(context, dict) else None
        if isinstance(agent_input, dict) and agent_input:
            chat_history.add_system_message(
                "CONTEXT (use to resolve workspace/SID, do not expose verbatim):\n"
                + json.dumps(agent_input, ensure_ascii=False)
            )

        for msg in messages:
            if msg.role == "user":
                chat_history.add_user_message(msg.content)
            elif msg.role == "assistant":
                chat_history.add_assistant_message(msg.content)

        chat_service = self.kernel.get_service(service_id="azure_openai_chat")
        execution_settings = chat_service.get_prompt_execution_settings_class()(
            function_choice_behavior="auto",
            max_completion_tokens=1200,
        )

        response = await chat_service.get_chat_message_content(
            chat_history=chat_history,
            settings=execution_settings,
            kernel=self.kernel,
        )

        content = str(response.content) if response and getattr(response, "content", None) else ""
        content = content.strip()
        if not content:
            content = "I couldn't produce a response. Please try again."

        self.tracer.step(
            "response_generation",
            "decision",
            "Generated final answer from tool loop",
            output_snapshot=sanitize_snapshot({"response_length": len(content)}),
        )

        return ChatResponse(
            messages=[ChatMessage(role="assistant", content=content)],
            reasoning_trace=self.tracer.get_trace(),
            metadata=None,
        )

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

    async def run(
        self,
        messages: list[ChatMessage],
        context: Optional[dict] = None,
    ) -> ChatResponse:
        """Handle structured execution requests (Agent interface implementation).

        Primary mode: agentic LLM+tools loop (model chooses tools; GuardFilter enforces safety).
        Optional mode: async execution/job status queries if enabled.

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

            return await self._run_agentic(messages, context)

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
