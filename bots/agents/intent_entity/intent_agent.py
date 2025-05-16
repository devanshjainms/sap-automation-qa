import json
import logging
import os
from pathlib import Path
from azure.identity import DefaultAzureCredential
from openai import AzureOpenAI
from bots.common.state import StateStore
from jinja2 import Environment, FileSystemLoader, select_autoescape


class IntentAgent:
    """
    Agent to extract user intent and entities using Azure OpenAI with Jinja templating.
    """

    def __init__(
        self,
        state_store: StateStore,
    ):
        self.endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-3.5-turbo")
        self.logger = logging.getLogger(self.__class__.__name__)
        self.state = state_store
        current_dir = Path(__file__).parent
        prompts_dir = current_dir / "prompts"
        self.jinja_env = Environment(
            loader=FileSystemLoader(prompts_dir), autoescape=select_autoescape(["j2"])
        )

        credential = DefaultAzureCredential()
        self.client = AzureOpenAI(
            azure_endpoint=self.endpoint,
            azure_deployment=self.deployment,
            azure_ad_token=credential,
            api_version="2025-04-01-preview",
        )

    def extract(self, text: str) -> tuple[str, dict]:
        """
        Calls Azure OpenAI to extract intent and entities from user text.

        Returns:
            intent (str): The detected intent label.
            entities (dict): Mapping of entity names to values.
        """
        system_prompt = self.jinja_env.get_template("system_prompt.j2").render()
        user_prompt = self.jinja_env.get_template("user_prompt.j2").render(message=text)

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

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            self.logger.error("Failed to parse JSON from OpenAI response", exc_info=e)
            raise

        intent = parsed.get("intent", "").strip()
        entities = parsed.get("entities", {}) or {}

        return intent, entities
