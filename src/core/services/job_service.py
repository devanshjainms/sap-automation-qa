# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Stateless application service for job orchestration (P1-WP-005B/C/D).
"""

from __future__ import annotations
from typing import List, Optional
from src.core.contracts.job_execution import JobExecutionPort
from src.core.contracts.storage import JobStoreProtocol
from src.core.execution.capability_classification import get_capability
from src.core.execution.test_catalog import (
    TEST_GROUP_PLAYBOOKS,
    resolve_offline_test_ids,
)
from src.core.models.job import (
    CreateJobRequest,
    Job,
    JobEvent,
    JobHistoryQuery,
    JobListResponse,
    JobStatus,
)
from src.core.observability import get_logger
from src.core.contracts.workspace import WorkspaceReader

logger = get_logger(__name__)


class JobApplicationService:
    """
    Stateless service for job submission, query, and cancellation.

    :param job_store: Storage backend for job operations.
    :param workspace_reader: Reader for workspace validation.
    :param execution_port: Narrow port to the single embedded ``JobWorker``
        for in-process submission and cancellation (`RD-021`/`RD-022`).
        There is no distributed-coordination fallback: this port is the
        only way a persisted job is scheduled for execution.
    """

    def __init__(
        self,
        job_store: JobStoreProtocol,
        workspace_reader: WorkspaceReader,
        execution_port: JobExecutionPort,
    ) -> None:
        self._job_store = job_store
        self._workspace_reader = workspace_reader
        self._execution_port = execution_port

    def list_jobs(
        self,
        workspace_id: Optional[str] = None,
        status: Optional[JobStatus | str] = None,
        active_only: bool = False,
        limit: int = 50,
    ) -> JobListResponse:
        """List execution jobs with optional filters.

        :param workspace_id: Filter by workspace identifier.
        :param status: Filter by job status.
        :param active_only: If ``True``, return only active (non-terminal) jobs.
        :param limit: Maximum number of jobs to return.
        :return: Response containing matching jobs and a total count.
        :raises ValueError: If ``status`` is not a valid ``JobStatus`` value.
        """
        status_filter: Optional[JobStatus] = None
        if status is not None:
            if isinstance(status, str):
                try:
                    status_filter = JobStatus(status)
                except ValueError as exc:
                    raise ValueError(
                        f"Invalid status '{status}'. "
                        f"Valid values: {[s.value for s in JobStatus]}"
                    ) from exc
            else:
                status_filter = status

        if active_only:
            jobs = self._job_store.get_active(workspace_id=workspace_id)
        else:
            jobs = self._job_store.get_history(
                JobHistoryQuery(
                    workspace_id=workspace_id,
                    status=status_filter,
                    limit=limit,
                )
            )
            jobs = self._job_store.get_active(workspace_id=workspace_id) + jobs

        if limit:
            jobs = jobs[:limit]

        return JobListResponse(jobs=jobs, total=len(jobs))

    def get_job(self, job_id: str) -> Optional[Job]:
        """Retrieve a single job by identifier.

        :param job_id: Unique job identifier.
        :return: The job, or ``None`` if not found.
        """
        return self._job_store.get(job_id)

    def get_job_events(self, job_id: str) -> Optional[List[JobEvent]]:
        """Retrieve events for a job.

        :param job_id: Unique job identifier.
        :return: List of events, or ``None`` if the job does not exist.
        """
        job = self._job_store.get(job_id)
        if job is None:
            return None
        return list(job.events)

    def get_jobs_for_schedule(self, schedule_id: str, limit: int = 50) -> List[Job]:
        """Retrieve jobs triggered by a specific schedule.

        :param schedule_id: Schedule identifier.
        :param limit: Maximum number of jobs to return.
        :return: List of jobs for the schedule.
        """
        return self._job_store.get_jobs_for_schedule(schedule_id, limit=limit)

    async def submit_job(self, request: CreateJobRequest) -> Job:
        """Validate a job request, persist it as PENDING, and hand it off.

        The persisted job is handed to the embedded worker for in-process
        execution exactly once, via the required execution port
        (`RD-021`/`RD-022`).

        :param request: The creation request containing workspace and test details.
        :return: The persisted pending job.
        :raises ValueError: If the workspace is not found, the test_group is
            invalid, or offline validation constraints are violated.
        :raises WorkspaceLockError: If the workspace already has an active job.
        """
        self._validate_workspace(request.workspace_id)
        self._validate_test_group(request.test_group)

        test_ids = request.test_ids
        if request.offline:
            test_ids = self._validate_offline(request.test_group, request.test_ids)

        job = Job(
            workspace_id=request.workspace_id,
            test_group=request.test_group,
            test_ids=test_ids,
            actor=request.actor,
            approval_ref=request.approval_ref,
            incident_ticket=request.incident_ticket,
            offline=request.offline,
        )

        self._job_store.create(job)
        try:
            self._execution_port.submit(job)
        except Exception as exc:
            job.fail(f"Failed to schedule job: {exc}")
            self._job_store.update(job)
            raise
        logger.info(
            "Submitted job %s for workspace %s",
            job.id,
            request.workspace_id,
        )
        return job

    async def cancel_job(
        self,
        job_id: str,
        reason: str = "Cancelled by user",
    ) -> bool:
        """Request cancellation of a running job.

        Cancellation is dispatched directly to the embedded worker so it
        can terminate the owned subprocess/task immediately.

        :param job_id: Identifier of the job to cancel.
        :param reason: Human-readable cancellation reason.
        :return: ``True`` if cancellation was requested; ``False`` otherwise.
        """
        return self._execution_port.cancel(job_id, reason)

    def _validate_workspace(self, workspace_id: str) -> None:
        """Validate that a workspace exists.

        :param workspace_id: Workspace identifier to check.
        :raises ValueError: If the workspace is not found.
        """
        known_ids = {ws.workspace_id for ws in self._workspace_reader.list_workspaces()}
        if workspace_id not in known_ids:
            raise ValueError(f"Workspace '{workspace_id}' not found")

    @staticmethod
    def _validate_test_group(test_group: Optional[str]) -> None:
        """Validate a test group name if provided.

        :param test_group: Test group to validate.
        :raises ValueError: If the test group is unknown.
        """
        if test_group and test_group not in TEST_GROUP_PLAYBOOKS:
            raise ValueError(
                f"Unknown test_group '{test_group}'. "
                f"Valid values: {sorted(TEST_GROUP_PLAYBOOKS)}"
            )

    @staticmethod
    def _validate_offline(
        test_group: Optional[str],
        test_ids: list[str],
    ) -> list[str]:
        """Validate and resolve offline execution constraints.

        :param test_group: Test group for offline execution.
        :param test_ids: Requested test IDs (may be empty).
        :return: Resolved offline test IDs.
        :raises ValueError: If offline constraints are violated.
        """
        if not test_group:
            raise ValueError("offline=true requires a test_group")
        get_capability(test_group).for_dispatch(offline=True)
        return list(resolve_offline_test_ids(test_group, test_ids))
