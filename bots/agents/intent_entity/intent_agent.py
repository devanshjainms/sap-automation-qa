import json
import logging
import os
from pathlib import Path
from typing import List
from openai import AzureOpenAI
from autogen_agentchat.messages import ChatMessage, TextMessage
from autogen_agentchat.agents import BaseChatAgent
from bots.common.state import StateStore
from jinja2 import Environment, FileSystemLoader, select_autoescape


class IntentAgent(BaseChatAgent):
    """
    Agent to extract user intent and entities using Azure OpenAI with Jinja templating.
    """

    def __init__(
        self,
        client: AzureOpenAI,
        state_store: StateStore,
    ):
        super().__init__(name="IntentAgent", description="Extracts user intent and entities.")

        self.logger = logging.getLogger(self.__class__.__name__)
        self.state = state_store
        current_dir = Path(__file__).parent
        prompts_dir = current_dir / "prompts"
        self.jinja_env = Environment(
            loader=FileSystemLoader(prompts_dir), autoescape=select_autoescape(["j2"])
        )
        self.client = client
        self.deployment = "gpt-3.5-turbo"
        self._buffer: List[ChatMessage] = []

    def on_reset(self) -> None:
        """Reset internal state for a new conversation."""
        self._buffer.clear()
    
    @property
    def produced_message_types(self) -> List[TextMessage]:
        """Specify that this agent produces text messages."""
        return [TextMessage]

    def on_messages(self, message: str) -> str:
        session_id = self.state.create_session(message)
        system_prompt = self.jinja_env.get_template("system_prompt.j2").render()
        user_prompt = self.jinja_env.get_template("user_prompt.j2").render(message=message)

        response = self.client.chat.completions.create(
            deployment_id=self.deployment,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            max_tokens=256,
        )
        content = response.choices[0].message.content.strip()
        self.logger.debug(f"Raw intent response: {content}")

        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            self.logger.error("Invalid JSON from intent model: %s", content)
            return ChatMessage(
                role="agent", content=json.dumps({"intent": "unknown", "entities": {}})
            )

        intent = result.get("intent", "")
        entities = result.get("entities", {})
        self.state.save_intent(session_id, intent)
        self.state.save_entities(session_id, entities)

        payload = json.dumps({"session_id": session_id, "intent": intent, "entities": entities})
        return ChatMessage(role="agent", content=payload)

    def on_messages_stream(self, messages: List[ChatMessage]) -> ChatMessage:
        """
        Streaming not required; delegate to on_messages.
        """
        return self.on_messages(messages)
