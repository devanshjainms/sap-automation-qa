# orchestrator.py

import os
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import TextMentionTermination
from transformers import pipeline
from src.agents.planner_agent import TestPlannerAgentFactory
from src.agents.executor_agent import ExecutorAgentFactory
from src.agents.monitor_agent import MonitorAgentFactory


def infer_test_type(user_request: str) -> str:
    """
    Infers the test type from the user request using a text classification model.
    """
    intent_classifier = pipeline(
        "text-classification", model="distilbert-base-uncased-finetuned-sst-2-english"
    )

    intent = intent_classifier(user_request)[0]["label"]
    return intent.lower()


def load_test_docs(test_type: str) -> str:
    doc_map = {"scs": "docs/SCS_HA.md", "db": "docs/DB_HA.md"}
    doc_file = doc_map.get(test_type.lower())
    if doc_file and os.path.exists(doc_file):
        with open(doc_file) as f:
            return f.read()
    return f"[No documentation found for test type: {test_type}]"


def load_test_catalog() -> str:
    file_path = "src/vars/input-api.py"
    if os.path.exists(file_path):
        with open(file_path) as f:
            return f.read()
    return "[Test catalog not found]"


def start_conversation(user_request: str):
    # Infer test type
    test_type = infer_test_type(user_request)

    # Load relevant docs
    docs_context = load_test_docs(test_type)
    catalog_context = load_test_catalog()

    # Create agents
    test_planner = TestPlannerAgentFactory.create()
    executor = ExecutorAgentFactory.create()
    monitor = MonitorAgentFactory.create()

    # Create group chat
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

    group_chat.run_stream(task=full_prompt)


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

    start_conversation(user_request=args.request)
