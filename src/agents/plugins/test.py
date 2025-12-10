# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Semantic Kernel plugin for SAP HA test planning.
"""

import yaml
import json
import logging
from typing import Annotated
from pathlib import Path
from datetime import datetime

from semantic_kernel.functions import kernel_function
from src.agents.models.test import PlannedTest, TestPlan
from src.agents.logging_config import get_logger

logger = get_logger(__name__)


class TestPlannerPlugin:
    """Semantic Kernel plugin for SAP test planning and recommendations."""

    def __init__(self, test_config_path: str = "src/vars/input-api.yaml"):
        """Initialize TestPlannerPlugin.

        :param test_config_path: Path to input-api.yaml with test definitions
        :type test_config_path: str
        """
        self.test_config_path = test_config_path
        self._last_generated_plan = None
        logger.info(f"TestPlannerPlugin initialized with config: {test_config_path}")

    @kernel_function(
        name="list_test_groups",
        description="List all available test groups (HA_DB_HANA, HA_SCS, etc.) "
        + f"from the test configuration",
    )
    def list_test_groups(
        self,
    ) -> Annotated[str, "JSON string with test group names and descriptions"]:
        """List all available test groups.

        :returns: JSON string with test groups
        :rtype: str
        """
        try:
            with open(self.test_config_path, "r") as f:
                config = yaml.safe_load(f)

            test_groups = config.get("test_groups", [])
            groups_info = []
            for group in test_groups:
                groups_info.append(
                    {"name": group.get("name"), "test_count": len(group.get("test_cases", []))}
                )

            result = {"test_groups": groups_info, "total_groups": len(groups_info)}

            logger.info(f"Retrieved {len(groups_info)} test groups")
            return json.dumps(result, indent=2)

        except Exception as e:
            logger.error(f"Error listing test groups: {e}")
            return json.dumps({"error": str(e)})

    @kernel_function(
        name="get_test_cases_for_group",
        description="Get all test cases for a specific test group (e.g., HA_DB_HANA or HA_SCS)",
    )
    def get_test_cases_for_group(
        self, test_group: Annotated[str, "The test group name (e.g., 'HA_DB_HANA', 'HA_SCS')"]
    ) -> Annotated[str, "JSON string with test cases for the group"]:
        """Get test cases for a specific test group.

        :param test_group: Name of the test group (e.g., HA_DB_HANA)
        :type test_group: str
        :returns: JSON string with test cases
        :rtype: str
        """
        try:
            with open(self.test_config_path, "r") as f:
                config = yaml.safe_load(f)

            test_groups = config.get("test_groups", [])
            matching_group = None
            for group in test_groups:
                if group.get("name") == test_group:
                    matching_group = group
                    break

            if not matching_group:
                return json.dumps(
                    {
                        "error": f"Test group '{test_group}' not found",
                        "available_groups": [g.get("name") for g in test_groups],
                    }
                )
            test_cases = []
            for test_case in matching_group.get("test_cases", []):
                test_cases.append(
                    {
                        "name": test_case.get("name"),
                        "task_name": test_case.get("task_name"),
                        "description": test_case.get("description", "").strip(),
                        "enabled": test_case.get("enabled", False),
                    }
                )

            result = {
                "test_group": test_group,
                "test_cases": test_cases,
                "total_tests": len(test_cases),
            }

            logger.info(f"Retrieved {len(test_cases)} test cases for group {test_group}")
            return json.dumps(result, indent=2)

        except Exception as e:
            logger.error(f"Error getting test cases for group {test_group}: {e}")
            return json.dumps({"error": str(e)})

    @kernel_function(
        name="list_applicable_tests",
        description="List all tests that are applicable based on system capabilities "
        + f"(HANA, HA cluster type, SCS, etc.)",
    )
    def list_applicable_tests(
        self,
        capabilities_json: Annotated[
            str,
            "JSON string containing system capabilities from get_system_capabilities_for_workspace()",
        ],
    ) -> Annotated[
        str, "JSON string with applicable tests, organized by category and safety level"
    ]:
        """Filter tests based on system capabilities.

        This function matches test requirements against actual system capabilities to determine
        which tests are applicable. It NEVER infers capabilities - all decisions are based on
        the provided capabilities dict.

        :param capabilities_json: JSON string with system capabilities
        :type capabilities_json: str
        :returns: JSON string with applicable tests categorized by type and safety
        :rtype: str
        """
        try:
            capabilities = json.loads(capabilities_json)
            if "error" in capabilities:
                return json.dumps(
                    {"error": f"Cannot determine applicable tests: {capabilities['error']}"}
                )
            with open(self.test_config_path, "r") as f:
                config = yaml.safe_load(f)
            test_groups = config.get("test_groups", [])
            safe_tests = []
            destructive_tests = []

            def requirements_met(test_requires: list[str], caps: dict) -> bool:
                """Check if all test requirements are satisfied by capabilities."""
                for req in test_requires:
                    if req not in caps or not caps.get(req):
                        return False
                return True

            def generate_reason(test_requires: list[str], caps: dict, test_group: str) -> str:
                """Generate explanation for why test is applicable."""
                met_requirements = [req for req in test_requires if caps.get(req)]
                if test_group == "HA_DB_HANA":
                    cluster_info = (
                        f"database cluster (type: {caps.get('database_cluster_type', 'N/A')})"
                    )
                else:
                    cluster_info = f"SCS cluster (type: {caps.get('scs_cluster_type', 'N/A')})"
                return f"Applicable because system has: {', '.join(met_requirements)} with {cluster_info}"

            for group in test_groups:
                group_name = group.get("name")

                for test_case in group.get("test_cases", []):
                    if not test_case.get("enabled", False):
                        continue
                    test_requires = test_case.get("requires", [])

                    if not requirements_met(test_requires, capabilities):
                        continue
                    test_info = {
                        "test_id": test_case.get("task_name"),
                        "test_name": test_case.get("name"),
                        "test_group": group_name,
                        "description": test_case.get("description", "").strip(),
                        "destructive": test_case.get("destructive", False),
                        "requires": test_requires,
                        "reason": generate_reason(test_requires, capabilities, group_name),
                    }

                    if test_info["destructive"]:
                        destructive_tests.append(test_info)
                    else:
                        safe_tests.append(test_info)

            result = {
                "workspace_id": capabilities.get("workspace_id"),
                "sap_sid": capabilities.get("sap_sid"),
                "db_sid": capabilities.get("db_sid"),
                "safe_tests": {
                    "count": len(safe_tests),
                    "tests": safe_tests,
                    "description": "These tests validate configuration and perform non-disruptive checks",
                },
                "destructive_tests": {
                    "count": len(destructive_tests),
                    "tests": destructive_tests,
                    "description": "WARNING: These tests simulate failures and may cause service disruption (node crashes, process kills, network isolation, filesystem freezing, etc.)",
                },
                "capabilities_used": {
                    "hana": capabilities.get("hana"),
                    "database_high_availability": capabilities.get("database_high_availability"),
                    "database_cluster_type": capabilities.get("database_cluster_type"),
                    "scs_high_availability": capabilities.get("scs_high_availability"),
                    "ascs_ers": capabilities.get("ascs_ers"),
                    "scs_cluster_type": capabilities.get("scs_cluster_type"),
                },
            }

            logger.info(
                f"Filtered tests for {capabilities.get('sap_sid')}: {len(safe_tests)} safe, {len(destructive_tests)} destructive"
            )
            return json.dumps(result, indent=2)

        except Exception as e:
            logger.error(f"Error filtering applicable tests: {e}")
            return json.dumps({"error": str(e)})

    def build_test_plan(self, capabilities: dict, applicable_tests_result: dict) -> TestPlan:
        """Build a structured TestPlan object from capabilities and applicable tests.

        This constructs the machine-readable contract between TestPlannerAgent and executors.

        :param capabilities: System capabilities dict
        :type capabilities: dict
        :param applicable_tests_result: Result from list_applicable_tests()
        :type applicable_tests_result: dict
        :returns: TestPlan object with all metadata
        :rtype: TestPlan
        """
        safe_planned_tests = [
            PlannedTest(
                test_id=test["test_id"],
                test_name=test["test_name"],
                test_group=test["test_group"],
                description=test["description"],
                destructive=test["destructive"],
                requires=test["requires"],
                reason=test["reason"],
            )
            for test in applicable_tests_result.get("safe_tests", {}).get("tests", [])
        ]

        destructive_planned_tests = [
            PlannedTest(
                test_id=test["test_id"],
                test_name=test["test_name"],
                test_group=test["test_group"],
                description=test["description"],
                destructive=test["destructive"],
                requires=test["requires"],
                reason=test["reason"],
            )
            for test in applicable_tests_result.get("destructive_tests", {}).get("tests", [])
        ]

        test_plan = TestPlan(
            workspace_id=capabilities.get("workspace_id", ""),
            sap_sid=capabilities.get("sap_sid", ""),
            db_sid=capabilities.get("db_sid"),
            capabilities=applicable_tests_result.get("capabilities_used", {}),
            safe_tests=safe_planned_tests,
            destructive_tests=destructive_planned_tests,
            total_tests=0,
            plan_metadata={
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "agent_version": "semantic_kernel_1.0",
                "test_config_path": self.test_config_path,
            },
        )

        return test_plan

    @kernel_function(
        name="generate_test_plan",
        description="Generate a complete structured test plan for a system based on capabilities."
        + f" Returns machine-readable TestPlan JSON.",
    )
    def generate_test_plan(
        self,
        workspace_id: Annotated[str, "Workspace ID (e.g., DEV-WEEU-SAP01-X00)"],
        capabilities_json: Annotated[
            str,
            "JSON string containing system capabilities from get_system_capabilities_for_workspace()",
        ],
    ) -> Annotated[str, "JSON string with complete TestPlan including safe and destructive tests"]:
        """Generate complete structured TestPlan from capabilities.

        This is the main function for creating machine-readable test plans.
        It combines capability checking with test filtering to produce a TestPlan object.

        :param workspace_id: Target workspace identifier
        :type workspace_id: str
        :param capabilities_json: JSON string with system capabilities
        :type capabilities_json: str
        :returns: JSON string with complete TestPlan
        :rtype: str
        """
        try:
            capabilities_data = json.loads(capabilities_json)
            if "error" in capabilities_data:
                return json.dumps(
                    {"error": f"Cannot generate test plan: {capabilities_data['error']}"}
                )
            if "capabilities" in capabilities_data:
                capabilities = capabilities_data["capabilities"]
                extracted_workspace_id = capabilities_data.get("workspace_id", workspace_id)
            else:
                capabilities = capabilities_data
                extracted_workspace_id = workspace_id
            capabilities["workspace_id"] = extracted_workspace_id

            applicable_tests_json = self.list_applicable_tests(json.dumps(capabilities))
            applicable_tests_result = json.loads(applicable_tests_json)

            if "error" in applicable_tests_result:
                return json.dumps({"error": applicable_tests_result["error"]})

            test_plan = self.build_test_plan(capabilities, applicable_tests_result)
            self._last_generated_plan = test_plan
            test_plan_dict = test_plan.model_dump()

            logger.info(
                f"Generated TestPlan for {test_plan.workspace_id}: {test_plan.total_tests} total "
                + f"tests ({len(test_plan.safe_tests)} safe, {len(test_plan.destructive_tests)} "
                + "destructive)"
            )

            return json.dumps(test_plan_dict, indent=2)

        except Exception as e:
            logger.error(f"Error generating test plan: {e}")
            return json.dumps({"error": str(e)})
