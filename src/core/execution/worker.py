# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Single-owner in-process worker for async test execution.
"""

from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from src.core.contracts.storage import JobLifecycleProtocol
from src.core.contracts.workspace import WorkspaceMaterializer
from src.core.execution.exceptions import CredentialProvisionError
from src.core.execution.executor import ExecutorProtocol
from src.core.execution.ssh_provider import SshCredentialProvider
from src.core.execution.test_catalog import resolve_offline_test_ids
from src.core.models.job import Job, JobStatus
from src.core.models.workspace import MaterializedWorkspace, mutable_workspace_vars
from src.core.observability import ExecutionScope, create_execution_event, get_logger

logger = get_logger(__name__)


@dataclass
class _ExecutionControl:
    """Tracks worker-local state for one submitted job.

    The FastAPI process that submits a job owns this job's asyncio task
    and subprocess handle for its entire lifetime — there is no durable
    lease, owner ID, or cancellation poll to reconcile against storage.
    """

    task: asyncio.Task[None] | None
    cancel_requested: bool = False
    cancellation_reason: str | None = None


class JobWorker:
    """Single-owner in-process worker for async test execution."""

    def __init__(
        self,
        job_store: JobLifecycleProtocol,
        executor: ExecutorProtocol,
        workspace_backend: WorkspaceMaterializer,
        log_dir: Path,
        ssh_provider: SshCredentialProvider | None = None,
    ) -> None:
        """Initialize the job worker.

        :param job_store: Storage backend for job lifecycle operations.
        :param executor: Executor used to run tests and terminate processes.
        :param workspace_backend: Backend used to materialize and clean up workspaces.
        :param log_dir: Directory in which job logs are stored.
        :param ssh_provider: Optional provider used to provision SSH credentials.
        """
        self.job_store = job_store
        self.executor = executor
        self.workspace_backend = workspace_backend
        self._log_dir = log_dir
        self.ssh_provider = ssh_provider or SshCredentialProvider()
        self._controls: dict[str, _ExecutionControl] = {}
        logger.info("JobWorker initialized")

    def submit(self, job: Job) -> None:
        """Submit a persisted PENDING job for in-process execution.
        This process is the sole owner of the resulting asyncio task and
        subprocess handle for this job.

        :param job: Persisted job with :attr:`JobStatus.PENDING` status.
        :raises ValueError: If ``job`` is not currently PENDING.
        """
        if job.status != JobStatus.PENDING:
            raise ValueError(
                f"Cannot submit job {job.id} for execution: "
                f"status is {job.status}, expected PENDING"
            )
        job_id = str(job.id)
        control = _ExecutionControl(task=None)
        self._controls[job_id] = control
        control.task = asyncio.create_task(self._execute_job(job, control))

    def cancel(self, job_id: str, reason: str = "Cancelled by user") -> bool:
        """Cancel a job owned by this worker.
        Terminates the owned subprocess/task immediately in-process.

        :param job_id: Identifier of the job to cancel.
        :param reason: Human-readable cancellation reason.
        :return: True if a tracked, not-yet-finished job was signalled for
            cancellation; False if no such job is tracked by this worker.
        """
        control = self._controls.get(job_id)
        if control is None or control.task is None or control.task.done():
            return False
        control.cancel_requested = True
        control.cancellation_reason = reason
        self.executor.terminate_process(job_id)
        return True

    def recover_crashed_jobs(self) -> int:
        """
        Mark all persisted non-terminal jobs failed at startup.

        :return: Number of recovered jobs marked as failed.
        :rtype: int
        """
        recovered = 0
        reason = "Recovered at startup: job was still active when the worker process restarted"
        for job in self.job_store.get_active():
            job.fail(reason)
            self.job_store.update(job)
            recovered += 1

        if recovered:
            logger.info("Startup recovery marked %s job(s) as failed", recovered)
        return recovered

    async def shutdown(self, timeout: float = 30.0) -> None:
        """Shut down the worker gracefully and stop local executions.

        :param timeout: Maximum seconds to wait for running tasks to finish.
        """
        tasks: list[asyncio.Task[None]] = []
        for job_id, control in list(self._controls.items()):
            if control.task is None or control.task.done():
                continue
            control.cancel_requested = True
            control.cancellation_reason = control.cancellation_reason or "Worker shutdown"
            self.executor.terminate_process(job_id)
            tasks.append(control.task)

        if not tasks:
            logger.info("JobWorker shutdown: no running jobs")
            self._controls.clear()
            return

        logger.info(
            "JobWorker shutdown: requesting cancellation for %s running job(s)",
            len(tasks),
        )
        try:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("JobWorker shutdown timed out after %ss", timeout)
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        self._controls.clear()
        logger.info("JobWorker shutdown complete")

    async def _execute_job(self, job: Job, control: _ExecutionControl) -> None:
        """Execute a submitted job to a terminal state.

        :param job: The job to execute; must already be persisted as PENDING.
        :param control: Control tracking cancellation for this job.
        """
        job_id = str(job.id)
        start_time = time.perf_counter()
        ssh_credential = None
        materialized: MaterializedWorkspace | None = None

        async def _cleanup_resources() -> None:
            """Clean up workspace and SSH resources once."""
            nonlocal ssh_credential, materialized
            if materialized is not None:
                try:
                    await asyncio.to_thread(self.workspace_backend.cleanup, materialized)
                except Exception as cleanup_err:
                    logger.warning(
                        "Workspace cleanup failed for job %s workspace %s: %s",
                        job_id,
                        materialized.workspace_id,
                        cleanup_err,
                        exc_info=True,
                    )
            if ssh_credential:
                ssh_credential.cleanup()

        with ExecutionScope(execution_id=job_id, workspace_id=job.workspace_id):
            try:
                job.start()
                self.job_store.update(job)
                logger.event(
                    create_execution_event(
                        "job_start",
                        job_id=job_id,
                        workspace_id=job.workspace_id,
                        test_group=job.test_group,
                    )
                )

                materialized = await asyncio.to_thread(
                    self.workspace_backend.materialize,
                    job.workspace_id,
                    job_id,
                )
                inventory_path = materialized.inventory_path
                if not inventory_path:
                    raise ValueError(f"No inventory path for workspace {job.workspace_id}")

                workspace_dir = materialized.local_path
                extra_vars = mutable_workspace_vars(materialized.extra_vars)
                extra_vars["_workspace_directory"] = str(workspace_dir)

                private_key_path = None
                ssh_password = None
                if not job.offline:
                    ssh_credential = await asyncio.to_thread(
                        self._provision_ssh_credential,
                        workspace_id=job.workspace_id,
                        extra_vars=extra_vars,
                    )
                    if ssh_credential:
                        private_key_path = ssh_credential.private_key_path
                        ssh_password = ssh_credential.ssh_password
                        logger.info(
                            "SSH credential provisioned for workspace %s (type=%s)",
                            job.workspace_id,
                            ssh_credential.auth_type.value,
                        )

                results: list[dict[str, Any]] = []
                test_group = job.test_group or "ConfigurationChecks"
                test_ids = job.test_ids or []
                if not job.test_group and not test_ids:
                    raise ValueError("No tests specified for execution")
                if job.offline:
                    test_ids = list(resolve_offline_test_ids(test_group, test_ids))
                elif not test_ids:
                    test_ids = [""]

                self._log_dir.mkdir(parents=True, exist_ok=True)
                log_path = self._log_dir / f"{job_id}.log"
                log_path.write_text("", encoding="utf-8")
                job.log_file = str(log_path)
                self.job_store.update(job)

                for test_id in test_ids:
                    if control.cancel_requested:
                        break
                    try:
                        result = await asyncio.to_thread(
                            self.executor.run_test,
                            workspace_id=job.workspace_id,
                            test_id=test_id,
                            test_group=test_group,
                            inventory_path=inventory_path,
                            extra_vars=extra_vars,
                            log_file=log_path,
                            job_id=job_id,
                            private_key_path=private_key_path,
                            ssh_password=ssh_password,
                            offline=job.offline,
                        )
                    except Exception as exc:
                        result = {"status": "failed", "error": str(exc)}

                    if control.cancel_requested:
                        break

                    if result.get("status") == "failed":
                        results.append(
                            {
                                "test_id": test_id,
                                "status": "failed",
                                "error": result.get("error"),
                            }
                        )
                    else:
                        results.append({"test_id": test_id, "status": "success", "result": result})

                await _cleanup_resources()

                if control.cancel_requested:
                    reason = control.cancellation_reason or "Cancelled by user"
                    job.cancel(reason)
                    self.job_store.update(job)
                    logger.event(
                        create_execution_event(
                            "job_cancel",
                            job_id=job_id,
                            workspace_id=job.workspace_id,
                            reason=reason,
                            duration_ms=(time.perf_counter() - start_time) * 1000,
                        )
                    )
                    return

                all_success = all(result.get("status") == "success" for result in results)
                summary = {
                    "results": results,
                    "status": "success" if all_success else "partial",
                    "tests_run": len(results),
                    "tests_passed": sum(
                        1 for result in results if result.get("status") == "success"
                    ),
                    "tests_failed": sum(
                        1 for result in results if result.get("status") == "failed"
                    ),
                }
                if all_success:
                    job.complete(summary, f"All {len(results)} tests completed")
                else:
                    job.complete(
                        summary,
                        (
                            f"Completed: {summary['tests_passed']} passed, "
                            f"{summary['tests_failed']} failed"
                        ),
                    )
                self.job_store.update(job)
                logger.event(
                    create_execution_event(
                        "job_complete",
                        job_id=job_id,
                        workspace_id=job.workspace_id,
                        test_group=job.test_group,
                        tests_passed=summary["tests_passed"],
                        tests_failed=summary["tests_failed"],
                        duration_ms=(time.perf_counter() - start_time) * 1000,
                    )
                )
            except asyncio.CancelledError:
                await _cleanup_resources()
                if not job.is_terminal:
                    reason = control.cancellation_reason or "Cancelled by user"
                    job.cancel(reason)
                    self.job_store.update(job)
                raise
            except Exception as exc:
                await _cleanup_resources()
                if not job.is_terminal:
                    job.fail(str(exc))
                    self.job_store.update(job)
                    logger.event(
                        create_execution_event(
                            "job_fail",
                            job_id=job_id,
                            workspace_id=job.workspace_id,
                            error=str(exc),
                            duration_ms=(time.perf_counter() - start_time) * 1000,
                        )
                    )
            finally:
                self._controls.pop(job_id, None)

    def _provision_ssh_credential(self, workspace_id: str, extra_vars: dict[str, Any]) -> Any:
        """Provision SSH credentials for a workspace.

        :param workspace_id: Identifier of the workspace requiring credentials.
        :param extra_vars: Mutable workspace variables used for provisioning.
        :return: Provisioned SSH credential, or ``None`` when provisioning fails.
        """
        try:
            return self.ssh_provider.provision(workspace_id=workspace_id, extra_vars=extra_vars)
        except CredentialProvisionError:
            logger.warning(
                "SSH credential provisioning failed for workspace %s — "
                "Ansible will attempt default SSH auth",
                workspace_id,
                exc_info=True,
            )
            return None

    def get_running_job_ids(self) -> list[str]:
        """Get the identifiers of currently running jobs.

        :returns: Identifiers of jobs executing in this worker process.
        """
        return [
            job_id
            for job_id, control in self._controls.items()
            if control.task is not None and not control.task.done()
        ]
