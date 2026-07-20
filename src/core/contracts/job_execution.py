# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Narrow execution port required by ``JobApplicationService`` (RD-021/RD-022).
"""

from __future__ import annotations
from typing import Protocol, runtime_checkable
from src.core.models.job import Job


@runtime_checkable
class JobExecutionPort(Protocol):
    """
    Narrow in-process submission/cancellation contract satisfied by the
    single embedded ``JobWorker``.
    """

    def submit(self, job: Job) -> None:
        """Schedule direct in-process execution for a persisted PENDING job.

        :param job: Persisted job with ``JobStatus.PENDING`` status.
        """
        raise NotImplementedError

    def cancel(self, job_id: str, reason: str = "Cancelled by user") -> bool:
        """Cancel a job tracked by this worker's direct execution path.

        :param job_id: Identifier of the job to cancel.
        :param reason: Human-readable cancellation reason.
        :return: True if a tracked, not-yet-finished job was signalled for
            cancellation; False if no such job is tracked by this worker.
        """
        raise NotImplementedError
