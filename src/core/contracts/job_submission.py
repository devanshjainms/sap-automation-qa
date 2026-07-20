# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Narrow job submission protocol consumed by the scheduler.
"""

from __future__ import annotations
from typing import Protocol, runtime_checkable
from src.core.models.job import CreateJobRequest, Job


@runtime_checkable
class JobSubmissionProtocol(Protocol):
    """
    Narrow submission contract satisfied by ``JobApplicationService``.
    """

    async def submit_job(self, request: CreateJobRequest) -> Job:
        """Submit a validated job creation request.

        :param request: Job creation request.
        :return: Persisted pending job.
        """
        raise NotImplementedError
