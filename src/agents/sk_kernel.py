# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Semantic Kernel initialization for SAP QA agents.

This module creates and configures a Semantic Kernel instance
with Azure OpenAI chat completion service.
"""

import logging
import os
from typing import Optional

from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion

from src.agents.logging_config import get_logger

logger = get_logger(__name__)


def create_kernel(
    endpoint: Optional[str] = None,
    api_key: Optional[str] = None,
    deployment: Optional[str] = None,
) -> Kernel:
    """Create and configure a Semantic Kernel with Azure OpenAI.

    :param endpoint: Azure OpenAI endpoint URL (defaults to AZURE_OPENAI_ENDPOINT env var)
    :type endpoint: Optional[str]
    :param api_key: Azure OpenAI API key (defaults to AZURE_OPENAI_API_KEY env var)
    :type api_key: Optional[str]
    :param deployment: Azure OpenAI deployment name (defaults to AZURE_OPENAI_DEPLOYMENT env var)
    :type deployment: Optional[str]
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
            service_id="azure_openai_chat",
            deployment_name=deployment,
            endpoint=endpoint,
            api_key=api_key,
        )
    )

    logger.info("Semantic Kernel created successfully with Azure OpenAI service")

    return kernel
