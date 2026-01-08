# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Utility functions for ActionPlan validation and normalization.

This module provides post-processing utilities for ActionPlan objects.
These are NOT agent methods - they are infrastructure utilities called
AFTER the LLM produces a plan to ensure it's well-formed.

Design Philosophy:
- LLM produces the plan (autonomous decision-making)
- These utilities validate/normalize the output (infrastructure)
- This separation keeps agents pure AI agents without bypass methods
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

from src.agents.models.action import ActionPlan
from src.agents.observability import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


def normalize_action_plan(raw: str | dict) -> ActionPlan:
    """Normalize and validate a raw ActionPlan JSON or dict into ActionPlan model.

    This fills missing required fields (job_id, title, destructive) with
    sensible defaults so downstream systems receive a well-formed plan.

    This is a POST-PROCESSING utility, not an LLM bypass. It runs AFTER
    the LLM produces a plan to ensure the output is valid.

    :param raw: Raw JSON string or dict from LLM output
    :type raw: str | dict
    :returns: Validated ActionPlan model
    :rtype: ActionPlan
    :raises ValueError: If the input is invalid JSON or structure
    """
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON for ActionPlan: {e}") from e
    else:
        data = raw

    jobs = data.get("jobs", []) or []
    normalized_jobs: list[dict] = []
    for idx, j in enumerate(jobs):
        if not isinstance(j, dict):
            raise ValueError(f"ActionPlan job must be an object, got: {type(j)}")
        job = dict(j)
        
        # Fill missing job_id
        if "job_id" not in job or not job.get("job_id"):
            job["job_id"] = f"job-{idx+1}-{uuid.uuid4().hex[:6]}"
        
        # Fill missing title
        if "title" not in job or not job.get("title"):
            plugin = job.get("plugin_name") or job.get("plugin") or "unknown"
            func = job.get("function_name") or job.get("function") or "action"
            job["title"] = f"{plugin}.{func}"
        
        # Normalize field names
        if "function_name" not in job and "function" in job:
            job["function_name"] = job.pop("function")
        if "plugin_name" not in job and "plugin" in job:
            job["plugin_name"] = job.pop("plugin")
        
        # Fill missing arguments
        if "arguments" not in job or job["arguments"] is None:
            job["arguments"] = {}
        
        # Fill missing destructive flag
        if "destructive" not in job:
            job["destructive"] = False
        
        normalized_jobs.append(job)

    normalized: dict = dict(data)
    normalized["jobs"] = normalized_jobs

    try:
        plan = ActionPlan(**normalized)
    except Exception as e:
        logger.error(f"Failed to validate normalized ActionPlan: {e}")
        raise

    return plan
