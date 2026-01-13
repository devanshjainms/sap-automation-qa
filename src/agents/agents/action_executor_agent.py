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

from typing import Optional, TYPE_CHECKING

from semantic_kernel import Kernel

from src.agents.agents.base import SAPAutomationAgent
from src.agents.workspace.workspace_store import WorkspaceStore
from src.agents.plugins.execution import ExecutionPlugin
from src.agents.plugins.workspace import WorkspacePlugin
from src.agents.plugins.ssh import SSHPlugin
from src.agents.plugins.job_management import JobManagementPlugin
from src.agents.plugins.troubleshooting import TroubleshootingPlugin
from src.agents.execution import GuardLayer
from src.agents.observability import get_logger
from src.agents.prompts import ACTION_EXECUTOR_SYSTEM_PROMPT

if TYPE_CHECKING:
    from src.agents.execution import JobStore, JobWorker, ExecutionJob

logger = get_logger(__name__)


class ActionExecutorAgent(SAPAutomationAgent):
    """Agent for executing SAP QA actions with strong safety and environment gating.

    Uses Semantic Kernel with:
    - ExecutionPlugin: Provides test execution tools as SK functions
    - JobManagementPlugin: Query job status, history (LLM-callable)
    - WorkspacePlugin: Access workspace configuration
    - SSHPlugin: Run diagnostic commands on hosts
    - Kernel-level approval filters for safety constraints

    All job queries go through JobManagementPlugin tools, letting the LLM
    autonomously decide when to check job status.

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

        Registers ExecutionPlugin and JobManagementPlugin with Semantic Kernel.

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
        plugins: list[object] = [
            execution_plugin,
            WorkspacePlugin(workspace_store),
            SSHPlugin(),
            JobManagementPlugin(job_store=job_store),
            TroubleshootingPlugin(
                workspace_store=workspace_store,
                execution_plugin=execution_plugin,
            ),
        ]
        if getattr(execution_plugin, "keyvault_plugin", None) is not None:
            plugins.append(execution_plugin.keyvault_plugin)

        super().__init__(
            name="action_executor",
            description="Investigates problems, executes diagnostics, runs tests, and performs "
            + "actions on SAP systems. "
            + "Use this agent for: investigation, diagnosis, root cause analysis, "
            + "running tests, running configuration checks "
            + "checking cluster status, analyzing logs, executing commands. "
            + "Primary operational agent for SAP HA systems.",
            kernel=kernel,
            instructions=ACTION_EXECUTOR_SYSTEM_PROMPT,
            plugins=plugins,
        )
        self.workspace_store: WorkspaceStore = workspace_store
        self.execution_plugin: ExecutionPlugin = execution_plugin
        self.job_store: Optional[JobStore] = job_store
        self.job_worker: Optional[JobWorker] = job_worker
        self._async_enabled: bool = job_store is not None and job_worker is not None
        self.guard_layer: GuardLayer = GuardLayer(
            job_store=job_store, workspace_store=workspace_store
        )

        logger.info(
            f"ActionExecutorAgent initialized with SK plugins "
            f"(async_enabled={self._async_enabled})"
        )

    async def execute_async(
        self,
        workspace_id: str,
        test_ids: list[str],
        test_group: str,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        confirmed: bool = False,
    ) -> "ExecutionJob":
        """Start async test execution and return job for tracking.

        NOTE: This is an API/infrastructure method, not an LLM bypass.
        It's called by the orchestrator/API layer to start background execution,
        not by the agent during LLM reasoning.

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
        :param confirmed: Whether destructive action is confirmed
        :type confirmed: bool
        :returns: ExecutionJob for tracking
        :rtype: ExecutionJob
        :raises RuntimeError: If async execution not enabled or not confirmed
        """
        is_destructive = self.guard_layer.is_destructive(test_ids=test_ids)
        if is_destructive and not confirmed:
            raise RuntimeError(
                "Destructive action detected. Call execute_async with confirmed=True to proceed."
            )

        guard_result = self.guard_layer.check_execution(
            workspace_id=workspace_id,
            test_ids=test_ids,
            is_destructive=is_destructive,
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
