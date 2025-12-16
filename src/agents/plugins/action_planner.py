# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Semantic Kernel plugin for creating validated ActionPlans.

The LLM may propose an ActionPlan, but this plugin enforces schema validation and
exposes the most recent plan to the agent for structured attachment.

Enterprise goals:
- explicit contract
- deterministic validation
- clear failure modes
"""

from __future__ import annotations

import json
from typing import Annotated, Optional

from pydantic import ValidationError
from semantic_kernel.functions import kernel_function

from src.agents.models.action import ActionPlan
from src.agents.observability import get_logger

logger = get_logger(__name__)


class ActionPlannerPlugin:
    """Plugin that validates and stores the most recent ActionPlan."""

    def __init__(self) -> None:
        self._last_generated_plan: Optional[ActionPlan] = None

    @kernel_function(
        name="create_action_plan",
        description=(
            "Create a machine-readable ActionPlan JSON for the current user request. "
            "The ActionPlan is a list of jobs, each mapping to a tool invocation: "
            "{plugin_name, function_name, arguments}. "
            "Use plugin_name 'ssh' for remote diagnostics and 'execution' for running tests."
        ),
    )
    def create_action_plan(
        self,
        action_plan_json: Annotated[
            str,
            "JSON string matching the ActionPlan schema. Must include workspace_id, intent, jobs[].",
        ],
    ) -> Annotated[str, "Validated ActionPlan as JSON (or error)"]:
        try:
            data = json.loads(action_plan_json)
            plan = ActionPlan(**data)
            self._last_generated_plan = plan
            logger.info(
                "Created ActionPlan: "
                + f"workspace_id={plan.workspace_id}, intent={plan.intent}, jobs={len(plan.jobs)}"
            )
            return json.dumps(plan.model_dump(), indent=2)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.error(f"Invalid ActionPlan: {e}")
            return json.dumps({"error": "Invalid ActionPlan", "details": str(e)})
