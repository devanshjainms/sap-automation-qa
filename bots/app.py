import asyncio
import logging
import os
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.messages import ChatMessage, TextMessage
from autogen_agentchat.conditions import TextMentionTermination
from bots.common.state import StateStore
from bots.agents.intent_entity.intent_agent import IntentAgent
from bots.agents.config.config_agent import ConfigAgent


def configure_logging():
    level = os.getenv("STAF_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


async def main():
    """
    Main entry point for the STAF Chat CLI application.
    """
    configure_logging()
    logger = logging.getLogger("chat")

    db_path = os.getenv("STAF_STATE_DB", "state.db")
    state = StateStore(db_path)

    client = AzureOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-3.5-turbo"),
        azure_ad_token_provider=get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        ),
        api_version="2025-04-01-preview",
    )
    intent_agent = IntentAgent(client=client, state_store=state)
    config_agent = ConfigAgent(client=client, state_store=state)
    agents = [intent_agent, config_agent]
    chat = RoundRobinGroupChat(
        agents, termination_condition=TextMentionTermination("DONE"), max_turns=10
    )

    print("Welcome to STAF PoC Chat (Autogen). Type 'exit' to quit.")
    while True:
        user_input = input("> ").strip()
        if user_input.lower() in ("exit", "quit"):
            print("Goodbye.")
            break
        if not user_input:
            continue

        try:
            final_message = chat.run_stream(task=user_input)
            async for message in final_message:
                if isinstance(message, TextMessage):
                    print(f"Bot: {message.text}")
                elif isinstance(message, ChatMessage):
                    print(f"Chat: {message.content}")
        except Exception as e:
            logger.error("Chat execution error", exc_info=e)
            print("An error occurred during processing. Please try again.")
            continue


if __name__ == "__main__":
    asyncio.run(main())