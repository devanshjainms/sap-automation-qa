# base_agent.py
import os
from typing import Optional, Dict, Any

from autogen_agentchat.agents import UserProxyAgent, AssistantAgent
from autogen_ext.models.openai import AzureOpenAIChatCompletionClient
from azure.identity import ManagedIdentityCredential, get_bearer_token_provider


class BaseAgent:
    def __init__(
        self,
        name: str,
        role: str,
        system_message: str,
        tools: Optional[list] = None,
        is_conversable: bool = True,
        model_name: str = "gpt-4",
        api_version: str = "2024-07-01-preview",
    ):
        self.name = name
        self.role = role
        self.system_message = system_message
        self.is_conversable = is_conversable
        self.model_name = model_name
        self.tools = tools if tools is not None else []
        self.azure_openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.azure_deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")

        token_provider = get_bearer_token_provider(
            ManagedIdentityCredential(),
            "https://cognitiveservices.azure.com/",
        )
        self.azure_client = AzureOpenAIChatCompletionClient(
            model=self.model_name,
            api_version=api_version,
            azure_endpoint=self.azure_openai_endpoint,
            azure_ad_token_provider=token_provider,
            azure_deployment=self.azure_deployment_name,
            model_info={
                "json_output": True,
                "function_calling": True,
                "vision": True,
                "family": "unknown",
            },
        )

        self.agent = self._create_agent()

    def _create_agent(self):
        if self.is_conversable:
            return AssistantAgent(
                name=self.name,
                model_client=self.azure_client,
                tools=self.tools,
                system_message=self.system_message,
            )
        else:
            return UserProxyAgent(
                name=self.name,
                input_func=self.tools,
                description=self.system_message,
            )

    def get_agent(self):
        return self.agent
