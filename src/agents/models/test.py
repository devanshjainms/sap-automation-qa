# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Pydantic models for structured SAP HA test planning.

This module defines the contract between the TestPlannerAgent and any test executor.
The models ensure machine-readable test plans with proper metadata, requirements, and safety flags.
"""

from pydantic import BaseModel, Field
from typing import Optional


class PlannedTest(BaseModel):
    """A single test case selected for execution based on system capabilities.

    This model represents the contract for a planned test, including all metadata
    needed for execution and auditing.
    """

    test_id: str = Field(description="Unique test identifier from input-api.yaml (task_name)")

    test_name: str = Field(description="Human-readable test name from input-api.yaml")

    test_group: str = Field(description="Test group (HA_DB_HANA, HA_SCS, etc.)")

    description: str = Field(description="Detailed test description from input-api.yaml")

    destructive: bool = Field(
        description="True if test simulates failures (crashes, kills, network isolation, etc.)"
    )

    requires: list[str] = Field(
        default_factory=list,
        description="List of capability requirements (e.g., ['hana', 'database_high_availability'])",
    )

    reason: str = Field(
        description="LLM-generated explanation of why this test is applicable based on requires[] "
        "vs actual capabilities"
    )


class TestPlan(BaseModel):
    """Complete test plan for an SAP system based on actual capabilities.

    This model represents the machine-readable contract between the TestPlannerAgent
    and downstream execution systems (orchestrators, CI/CD pipelines, etc.).
    """

    workspace_id: str = Field(description="Target workspace identifier (e.g., DEV-WEEU-SAP01-X00)")

    sap_sid: str = Field(description="SAP System ID from configuration")

    db_sid: Optional[str] = Field(default=None, description="Database System ID if applicable")

    capabilities: dict = Field(
        description="System capabilities from sap-parameters.yaml used to generate this plan"
    )

    safe_tests: list[PlannedTest] = Field(
        default_factory=list, description="Non-destructive tests (configuration validation, checks)"
    )

    destructive_tests: list[PlannedTest] = Field(
        default_factory=list,
        description="Destructive tests that simulate failures (WARNING: causes service disruption)",
    )

    total_tests: int = Field(description="Total number of tests in this plan (safe + destructive)")

    plan_metadata: dict = Field(
        default_factory=dict,
        description="Additional metadata (generation timestamp, agent version, etc.)",
    )

    def model_post_init(self, __context) -> None:
        """Calculate total_tests after initialization."""
        self.total_tests = len(self.safe_tests) + len(self.destructive_tests)
