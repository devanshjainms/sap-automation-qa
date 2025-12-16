# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Pydantic models for unified action/job planning.

This contract represents *what to do* as an ordered list of jobs.
Each job maps directly to a Semantic Kernel tool invocation.

Design goals:
- Unify "diagnostics" and "test runs" under one plan type
- Keep execution deterministic and auditable
- Make plans validateable independent of the LLM
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ActionJob(BaseModel):
    """A single executable job represented as a tool invocation."""

    job_id: str = Field(description="Unique job identifier within the plan")
    title: str = Field(description="Human-readable job title")

    plugin_name: str = Field(description="Semantic Kernel plugin name (e.g., 'ssh', 'execution')")
    function_name: str = Field(description="Semantic Kernel function name")

    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Keyword arguments passed to the tool function",
    )

    destructive: bool = Field(
        default=False,
        description="True if job may cause disruption (e.g., crash/failover simulations)",
    )


class ActionPlan(BaseModel):
    """A unified plan for operational diagnostics and test execution."""

    workspace_id: str = Field(description="Target workspace identifier")
    sap_sid: Optional[str] = Field(default=None, description="SAP System ID if known")

    intent: str = Field(
        description="High-level intent label (e.g., 'diagnostic', 'test_run')",
    )

    jobs: list[ActionJob] = Field(default_factory=list, description="Ordered list of jobs")

    plan_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata (timestamps, versions, correlation IDs)",
    )

    generated_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z",
        description="UTC timestamp when this plan was generated",
    )

    def model_post_init(self, __context: Any) -> None:
        if "total_jobs" not in self.plan_metadata:
            self.plan_metadata["total_jobs"] = len(self.jobs)
