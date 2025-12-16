# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Semantic Kernel plugin for agent routing.

This plugin provides routing functions that help the orchestrator
choose the appropriate agent for handling user requests.
"""

import json
from typing import Annotated

from semantic_kernel.functions import kernel_function
from src.agents.observability import get_logger

logger = get_logger(__name__)


class AgentRoutingPlugin:
    """Semantic Kernel plugin for routing requests to appropriate agents.

    This plugin exposes routing functions that the LLM can call
    to route requests to the correct agent with appropriate parameters.
    """

    def __init__(self, agent_registry) -> None:
        """Initialize agent routing plugin.

        :param agent_registry: AgentRegistry containing available agents
        :type agent_registry: AgentRegistry
        """
        self.agent_registry = agent_registry
        logger.info("AgentRoutingPlugin initialized")

    @kernel_function(
        name="route_to_echo",
        description="Route to Echo agent ONLY for pure documentation questions, greetings, "
        + "or explaining how the framework works. Do NOT use for any operational requests like "
        + "checking status, running commands, viewing logs, or diagnostics - those go to action_executor.",
    )
    def route_to_echo(
        self,
    ) -> Annotated[str, "Routing decision as JSON"]:
        """Route to echo agent.

        :returns: JSON with agent_name and agent_input
        :rtype: str
        """
        logger.info("Routing to echo agent")
        return json.dumps({"agent_name": "echo", "agent_input": {}})

    @kernel_function(
        name="route_to_system_context",
        description="Route to System Context agent for workspace management. Use when user wants to: "
        + "list workspaces, find a workspace by SID/environment, get workspace details, "
        + "create a new workspace, or get SAP system parameters. "
        + "Parameters: sid (optional), env (optional).",
    )
    def route_to_system_context(
        self,
        sid: Annotated[str, "SAP System ID (SID), e.g., 'X00'"] = "",
        env: Annotated[str, "Environment name, e.g., 'DEV', 'QA', 'PROD'"] = "",
    ) -> Annotated[str, "Routing decision as JSON"]:
        """Route to system_context agent.

        :param sid: Optional SAP System ID
        :type sid: str
        :param env: Optional environment name
        :type env: str
        :returns: JSON with agent_name and agent_input
        :rtype: str
        """
        logger.info(f"Routing to system_context agent (sid={sid}, env={env})")
        agent_input = {}
        if sid:
            agent_input["sid"] = sid
        if env:
            agent_input["env"] = env

        return json.dumps({"agent_name": "system_context", "agent_input": agent_input})

    @kernel_function(
        name="route_to_test_advisor",
        description="Route to Test Advisor agent for test recommendations and planning. Use when user "
        + "asks about: what tests to run, test recommendations for a system, available tests, "
        + "test planning, or wants to generate a test plan. "
        + "Parameters: sid (required or inferred), env (optional), test_filter (optional).",
    )
    def route_to_test_advisor(
        self,
        sid: Annotated[str, "SAP System ID (SID), e.g., 'X00'"] = "",
        env: Annotated[str, "Environment name, e.g., 'DEV', 'QA'"] = "",
        test_filter: Annotated[str, "Optional test filter, e.g., 'HA_DB_HANA', 'HA_SCS'"] = "",
    ) -> Annotated[str, "Routing decision as JSON"]:
        """Route to test_advisor agent.

        :param sid: SAP System ID
        :type sid: str
        :param env: Optional environment name
        :type env: str
        :param test_filter: Optional test group filter
        :type test_filter: str
        :returns: JSON with agent_name and agent_input
        :rtype: str
        """
        logger.info(
            f"Routing to test_advisor agent (sid={sid}, env={env}, test_filter={test_filter})"
        )
        agent_input = {}
        if sid:
            agent_input["sid"] = sid
        if env:
            agent_input["env"] = env
        if test_filter:
            agent_input["test_filter"] = test_filter

        return json.dumps({"agent_name": "test_advisor", "agent_input": agent_input})

    @kernel_function(
        name="route_to_action_executor",
        description="Route to Action Executor agent for ANY operational request on SAP systems. "
        + "Use when user wants to: run tests, check cluster status, check Pacemaker status, "
        + "tail log files, view system messages, run diagnostics, execute SSH commands to hosts, "
        + "get HANA status, check SCS status, run 'crm status', run 'pcs status', or ANY command "
        + "that needs to be executed on remote SAP hosts. This is the primary agent for all "
        + "operational/diagnostic work. "
        + "Parameters: workspace_id (required), test_filter (optional), include_destructive (default: false).",
    )
    def route_to_action_executor(
        self,
        workspace_id: Annotated[str, "Workspace ID in format ENV-REGION-DEPLOYMENT-SID"] = "",
        sid: Annotated[str, "SAP System ID (SID), e.g., 'X00'"] = "",
        env: Annotated[str, "Environment name, e.g., 'DEV', 'QA'"] = "",
        test_filter: Annotated[str, "Optional test filter, e.g., 'HA_DB_HANA'"] = "",
        include_destructive: Annotated[
            bool, "Whether to include destructive tests (default: false)"
        ] = False,
    ) -> Annotated[str, "Routing decision as JSON"]:
        """Route to action_executor agent.

        :param workspace_id: Workspace ID
        :type workspace_id: str
        :param sid: SAP System ID
        :type sid: str
        :param env: Environment name
        :type env: str
        :param test_filter: Optional test group filter
        :type test_filter: str
        :param include_destructive: Whether to include destructive tests
        :type include_destructive: bool
        :returns: JSON with agent_name and agent_input
        :rtype: str
        """
        logger.info(
            f"Routing to action_executor agent (workspace_id={workspace_id}, sid={sid}, "
            + f"env={env}, test_filter={test_filter}, include_destructive={include_destructive})"
        )
        agent_input = {}
        if workspace_id:
            agent_input["workspace_id"] = workspace_id
        if sid:
            agent_input["sid"] = sid
        if env:
            agent_input["env"] = env
        if test_filter:
            agent_input["test_filter"] = test_filter
        if include_destructive:
            agent_input["include_destructive"] = include_destructive

        return json.dumps({"agent_name": "action_executor", "agent_input": agent_input})

    @kernel_function(
        name="list_available_agents",
        description="List all available agents with their names and descriptions. Use this to understand "
        + "what agents are available for routing.",
    )
    def list_available_agents(self) -> Annotated[str, "List of available agents as JSON"]:
        """List all available agents.

        :returns: JSON string with agent information
        :rtype: str
        """
        agents = self.agent_registry.list_agents()
        logger.info(f"Listed {len(agents)} available agents")
        return json.dumps({"agents": agents}, indent=2)
