# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Semantic Kernel initialization for SAP QA agents.

This module creates and configures a Semantic Kernel instance
with Azure OpenAI chat completion service. Supports per-agent
model deployment configuration.
"""

import logging
import os
from typing import Optional

from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from semantic_kernel.filters import FilterTypes

from src.agents.observability import get_logger
from src.agents.filters import ApprovalFilter

logger = get_logger(__name__)


def create_kernel(
    endpoint: Optional[str] = None,
    api_key: Optional[str] = None,
    deployment: Optional[str] = None,
    service_id: str = "azure_openai_chat",
) -> Kernel:
    """Create and configure a Semantic Kernel with Azure OpenAI.

    :param endpoint: Azure OpenAI endpoint URL (defaults to AZURE_OPENAI_ENDPOINT env var)
    :type endpoint: Optional[str]
    :param api_key: Azure OpenAI API key (defaults to AZURE_OPENAI_API_KEY env var)
    :type api_key: Optional[str]
    :param deployment: Azure OpenAI deployment name (defaults to AZURE_OPENAI_DEPLOYMENT env var)
    :type deployment: Optional[str]
    :param service_id: Service ID for the chat completion service (default: azure_openai_chat)
    :type service_id: str
    :returns: Configured Kernel instance with Azure OpenAI chat completion service
    :rtype: Kernel
    :raises ValueError: If required credentials are missing

    Example:
        >>> kernel = create_kernel()
        >>> # Kernel is now ready to use with plugins
    """
    endpoint = endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = api_key or os.getenv("AZURE_OPENAI_API_KEY")
    deployment = deployment or os.getenv("AZURE_OPENAI_DEPLOYMENT")
    if not endpoint:
        raise ValueError("AZURE_OPENAI_ENDPOINT not set")
    if not api_key:
        raise ValueError("AZURE_OPENAI_API_KEY not set")
    if not deployment:
        raise ValueError("AZURE_OPENAI_DEPLOYMENT not set")

    logger.info(f"Creating Semantic Kernel with endpoint: {endpoint}, deployment: {deployment}")
    kernel = Kernel()
    kernel.add_service(
        AzureChatCompletion(
            service_id=service_id,
            deployment_name=deployment,
            endpoint=endpoint,
            api_key=api_key,
        )
    )

    approval_filter = ApprovalFilter()
    kernel.add_filter(
        filter_type=FilterTypes.FUNCTION_INVOCATION,
        filter=approval_filter.on_function_invocation,
    )
    logger.info("Registered kernel approval filter for execution safety")

    logger.info("Semantic Kernel created successfully with Azure OpenAI service")

    return kernel


def add_chat_service(
    kernel: Kernel,
    deployment: str,
    service_id: str,
    endpoint: Optional[str] = None,
    api_key: Optional[str] = None,
) -> None:
    """Add an additional chat completion service to an existing kernel.

    Use this to add different model deployments for different agents.

    :param kernel: Existing Kernel instance
    :type kernel: Kernel
    :param deployment: Azure OpenAI deployment name for this service
    :type deployment: str
    :param service_id: Unique service ID for this chat service
    :type service_id: str
    :param endpoint: Azure OpenAI endpoint URL (defaults to env var)
    :type endpoint: Optional[str]
    :param api_key: Azure OpenAI API key (defaults to env var)
    :type api_key: Optional[str]

    Example:
        >>> kernel = create_kernel()  # Uses default deployment
        >>> add_chat_service(kernel, "gpt-4", "gpt4_service")
        >>> # Now kernel has two services: azure_openai_chat and gpt4_service
    """
    endpoint = endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = api_key or os.getenv("AZURE_OPENAI_API_KEY")

    if not endpoint or not api_key:
        raise ValueError("Azure OpenAI credentials not available")

    kernel.add_service(
        AzureChatCompletion(
            service_id=service_id,
            deployment_name=deployment,
            endpoint=endpoint,
            api_key=api_key,
        )
    )
    logger.info(f"Added chat service '{service_id}' with deployment '{deployment}'")
