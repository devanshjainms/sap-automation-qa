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
    - Kernel-level approval filters for safety constraints

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

        Registers ExecutionPlugin with Semantic Kernel agents.

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

        plugins: list[object] = [
            execution_plugin,
            WorkspacePlugin(workspace_store),
            SSHPlugin(),
        ]
        if getattr(execution_plugin, "keyvault_plugin", None) is not None:
            plugins.append(execution_plugin.keyvault_plugin)
        super().__init__(
            name="action_executor",
            description="Executes SAP QA actions, runs playbooks, performs configuration checks, "
            + "and runs functional tests (HA, crash, failover) using Ansible. "
            + "Use this agent whenever the user asks to 'run', 'execute', 'perform', or 'start' a test or action.",
            kernel=kernel,
            instructions=ACTION_EXECUTOR_SYSTEM_PROMPT,
            plugins=plugins,
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
