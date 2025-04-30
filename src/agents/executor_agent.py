# executor_agent.py

import subprocess
from autogen_core.tools import FunctionTool
from autogen_agentchat.agents import UserProxyAgent
from base_agent import BaseAgent


def run_ha_test() -> str:
    """
    Run the HA Ansible playbook for SAP failover testing.
    """
    try:
        result = subprocess.run(
            ["ansible-playbook", "/opt/ansible/ha_failover.yml"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        return f"[ERROR] HA test failed: {e.stderr}"


def run_config_validation() -> str:
    """
    Run a Python script to validate SAP system configuration.
    """
    try:
        result = subprocess.run(
            ["python3", "/opt/scripts/config_validation.py"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        return f"[ERROR] Configuration validation failed: {e.stderr}"


class ExecutorAgentFactory:
    @staticmethod
    def create() -> UserProxyAgent:
        system_message = (
            "You are the Executor agent. You execute Ansible playbooks or Python modules "
            "as instructed by the test planner. Use the 'execution_hint' provided to select the tool."
        )

        high_availability = FunctionTool(
            run_ha_test,
            name="RunHighAvailabilityFunctionalTest",
            description="Run the HA Ansible playbook for SAP failover testing.",
        )
        config_validation = FunctionTool(
            run_config_validation,
            name="RunClusterConfigurationValidation",
            description="Run a Python script to validate SAP system configuration.",
        )
        agent = BaseAgent(
            name="ExecutorAgent",
            role="executor",
            system_message=system_message,
            tools=[high_availability, config_validation],
            is_conversable=False,
        ).get_agent()

        return agent
