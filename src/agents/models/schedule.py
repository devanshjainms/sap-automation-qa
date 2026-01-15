# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Schedule models for automated test execution."""

from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from src.agents.models.job import JobStatus


class Schedule(BaseModel):
    """Schedule configuration for automated test execution across workspaces.

    Supports multi-workspace targeting - one schedule can trigger jobs
    on multiple workspaces simultaneously.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    description: str = ""
    cron_expression: str
    timezone: str = "UTC"
    workspace_ids: List[str] = Field(default_factory=list)
    test_group: Optional[str] = None
    test_ids: List[str] = Field(default_factory=list)
    enabled: bool = True
    next_run_time: Optional[datetime] = None
    last_run_time: Optional[datetime] = None
    last_run_job_ids: List[str] = Field(default_factory=list)
    consecutive_failures: int = 0
    total_runs: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        """Pydantic configuration."""

        use_enum_values = True


class ScheduleListResponse(BaseModel):
    """Response model for listing schedules."""

    schedules: List[Schedule]
    count: int


class CreateScheduleRequest(BaseModel):
    """Request model for creating a schedule."""

    name: str
    description: str = ""
    cron_expression: str
    timezone: str = "UTC"
    workspace_ids: List[str]
    test_group: Optional[str] = None
    test_ids: List[str] = Field(default_factory=list)
    enabled: bool = True


class UpdateScheduleRequest(BaseModel):
    """Request model for updating a schedule."""

    name: Optional[str] = None
    description: Optional[str] = None
    cron_expression: Optional[str] = None
    timezone: Optional[str] = None
    workspace_ids: Optional[List[str]] = None
    test_group: Optional[str] = None
    test_ids: Optional[List[str]] = None
    enabled: Optional[bool] = None
