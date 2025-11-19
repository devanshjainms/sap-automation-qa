# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Azure OpenAI client wrapper for the backend."""

import logging
import os
from typing import Any, Optional

from openai import AsyncAzureOpenAI

from src.agents.logging_config import get_logger

logger = get_logger(__name__)


class AzureOpenAIClient:
    """Minimal wrapper for Azure OpenAI Chat Completions API."""

    def __init__(
        self,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        deployment: Optional[str] = None,
    ) -> None:
        """
        Initialize Azure OpenAI client.

        :param endpoint: Azure OpenAI endpoint URL (defaults to env var)
        :type endpoint: Optional[str]
        :param api_key: Azure OpenAI API key (defaults to env var)
        :type api_key: Optional[str]
        :param deployment: Azure OpenAI deployment name (defaults to env var)
        :type deployment: Optional[str]
        :raises ValueError: If required credentials are missing
        """
        self.endpoint = endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
        self.api_key = api_key or os.getenv("AZURE_OPENAI_API_KEY")
        self.deployment = deployment or os.getenv("AZURE_OPENAI_DEPLOYMENT")

        logger.info(
            f"Initializing Azure OpenAI client: endpoint={self.endpoint}, deployment={self.deployment}"
        )

        if not self.endpoint:
            raise ValueError("AZURE_OPENAI_ENDPOINT not set")
        if not self.api_key:
            raise ValueError("AZURE_OPENAI_API_KEY not set")
        if not self.deployment:
            raise ValueError("AZURE_OPENAI_DEPLOYMENT not set")

        self.client = AsyncAzureOpenAI(
            azure_endpoint=self.endpoint,
            api_key=self.api_key,
            api_version="2024-02-01",
        )

    async def call_llm(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[str] = None,
    ) -> Any:
        """Call Azure OpenAI Chat Completions API.

        :param messages: List of message dicts with 'role' and 'content' keys
        :type messages: list[dict]
        :param tools: Optional list of tool/function specifications for function calling
        :type tools: Optional[list[dict]]
        :param tool_choice: Optional tool choice strategy ("auto", "none", or specific function)
        :type tool_choice: Optional[str]
        :returns: ChatCompletion response object from Azure OpenAI API
        :rtype: Any
        :raises Exception: If API call fails
        """
        logger.info(f"Calling Azure OpenAI with {len(messages)} messages")
        if tools:
            logger.info(f"Tools available: {len(tools)} functions")
        params = {
            "model": self.deployment,
            "messages": messages,
        }

        if tools:
            params["tools"] = tools
        if tool_choice:
            params["tool_choice"] = tool_choice

        response = await self.client.chat.completions.create(**params)
        logger.info("Azure OpenAI call successful")
        return response


_client: Optional[AzureOpenAIClient] = None


async def call_llm(
    messages: list[dict],
    tools: Optional[list[dict]] = None,
    tool_choice: Optional[str] = None,
) -> Any:
    """Call Azure OpenAI Chat Completions API using global client.

    :param messages: List of message dicts with 'role' and 'content' keys
    :type messages: list[dict]
    :param tools: Optional list of tool/function specifications for function calling
    :type tools: Optional[list[dict]]
    :param tool_choice: Optional tool choice strategy ("auto", "none", or specific function)
    :type tool_choice: Optional[str]
    :returns: ChatCompletion response object from Azure OpenAI API
    :rtype: Any
    :raises ValueError: If Azure OpenAI credentials not configured
    :raises Exception: If API call fails
    """
    global _client
    if _client is None:
        _client = AzureOpenAIClient()

    return await _client.call_llm(messages, tools=tools, tool_choice=tool_choice)
