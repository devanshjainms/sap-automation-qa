# orchestrator.py
import asyncio
import os
from autogen_agentchat.base import TaskResult
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import TextMentionTermination
from src.agents.planner_agent import TestPlannerAgentFactory
from src.agents.executor_agent import ExecutorAgentFactory
from src.agents.monitor_agent import MonitorAgentFactory
from src.agents.utils.logger import get_logger

logger = get_logger("Orchestrator")


def infer_test_type(user_request: str) -> str:
    """
    Infers the test type from the user request using a text classification model.
    """
    logger.info(f"Inferring test type for request: {user_request}")
    test_json = {
        "scs": ["central services", "scs", "failover"],
        "db": ["database", "db", "replication"],
        "performance": ["performance", "load test", "stress test"],
    }
    for test_type, keywords in test_json.items():
        if any(keyword.lower() in user_request.lower() for keyword in keywords):
            return test_type
    return input("Could not infer test type. Please specify: ")


def load_test_docs(test_type: str) -> str:
    doc_map = {"scs": "docs/SCS_HIGH_AVAILABILITY.md", "db": "docs/DB_HIGH_AVAILABILITY.md"}
    doc_file = doc_map.get(test_type.lower())
    if doc_file and os.path.exists(doc_file):
        with open(doc_file) as f:
            return f.read()
    return f"[No documentation found for test type: {test_type}]"


def load_test_catalog() -> str:
    file_path = "src/vars/input-api.yaml"
    if os.path.exists(file_path):
        with open(file_path) as f:
            logger.info("Loading test catalog")
            return f.read()
    return "[Test catalog not found]"


async def start_conversation(user_request: str):
    logger.info("Starting conversation")
    test_type = infer_test_type(user_request)

    docs_context = load_test_docs(test_type)
    catalog_context = load_test_catalog()

    test_planner = TestPlannerAgentFactory.create()
    executor = ExecutorAgentFactory.create()
    monitor = MonitorAgentFactory.create()
    logger.info("Agents created successfully")

    group_chat = RoundRobinGroupChat(
        participants=[test_planner, executor, monitor],
        termination_condition=TextMentionTermination("DONE"),
        max_turns=12,
    )
    full_prompt = (
        f"{user_request}\n\n"
        f"Reference these documents:\n\n"
        f"--- TEST CATALOG ---\n{catalog_context}\n\n"
        f"--- TEST DOCUMENT ({test_type.upper()}) ---\n{docs_context}\n"
    )
    logger.info("Running group chat ")
    group_chat.run_stream(task=full_prompt)

    async for task_result in group_chat.run_stream(task=full_prompt):
        if isinstance(task_result, TaskResult):
            logger.info(f"Stop Reason: {task_result.stop_reason}")
        else:
            logger.info(task_result)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Run SAP Automation QA Testing with AutoGen Agents (using Teams)"
    )
    parser.add_argument(
        "--request",
        required=True,
        help="User request describing the test (e.g., 'Plan and run HA failover test for SAP Central Services')",
    )
    args = parser.parse_args()

    asyncio.run(start_conversation(user_request=args.request))
