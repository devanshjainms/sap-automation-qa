# test_planner_agent.py

from src.agents.base_agent import BaseAgent


class TestPlannerAgentFactory:
    """
    Factory to initialize the TestPlannerAgent with role-specific logic.
    """

    @staticmethod
    def create():
        system_message = (
            "You are a SAP Automation QA Test Planner agent responsible for generating detailed QA test plans "
            "for SAP systems running on Azure. When given a scenario (e.g., 'HA test', "
            "'Configuration Validation'), you should return:\n\n"
            "- A list of specific test steps\n"
            "- Preconditions required\n"
            "- Target systems or components\n"
            "- Expected results\n"
            "- Ansible playbook or Python function to be invoked for each test\n\n"
            "Output should be in structured YAML format with keys: 'test_case_id', 'description', "
            "'steps', 'preconditions', 'expected_outcome', and 'execution_hint'."
        )

        return BaseAgent(
            name="TestPlannerAgent",
            role="planner",
            system_message=system_message,
            is_conversable=True,
        ).get_agent()
