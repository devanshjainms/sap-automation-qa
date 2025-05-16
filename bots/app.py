# chat.py - Production-ready CLI Chat Server Entry Point
import sys
import logging
import os
from bots.common.state import StateStore
from bots.agents.intent_entity.intent_agent import IntentAgent


def configure_logging():
    level = os.getenv("STAF_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    configure_logging()
    logger = logging.getLogger("chat")

    db_path = os.getenv("STAF_STATE_DB", "state.db")
    state = StateStore(db_path)
    intent_agent = IntentAgent(state_store=state)

    print("Welcome to STAF PoC Chat. Type 'exit' to quit.")
    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            logger.info("Chat interrupted by user, exiting.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            logger.info("User requested exit.")
            break

        session_id = state.create_session(user_input)
        logger.debug(f"Stored user message in session {session_id}")

        try:
            intent, entities = intent_agent.extract(user_input)
        except Exception as e:
            logger.error("Intent extraction failed", exc_info=e)
            print("Sorry, I couldn't understand that. Please try again.")
            continue

        state.save_intent(session_id, intent)
        state.save_entities(session_id, entities)

        # Display results
        print(f"Intent: {intent}")
        if entities:
            print("Entities:")
            for name, value in entities.items():
                print(f"  - {name}: {value}")
        else:
            print("Entities: None")

    print("Goodbye.")


if __name__ == "__main__":
    main()
