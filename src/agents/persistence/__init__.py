# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Chat persistence module for SAP QA Agent Framework.

This module provides persistent storage for:
- Conversation history
- Message transcripts
- Conversation summaries
- Reasoning traces

Supports SQLite for local development and can be extended
for Azure Cosmos DB in production deployments.
"""

from src.agents.models import (
    Conversation,
    ConversationSummary,
    ConversationWithMessages,
    Message,
    MessageRole,
    ReasoningTrace,
)
from src.agents.persistence.storage import ChatStorage
from src.agents.persistence.manager import ConversationManager

__all__ = [
    "ChatStorage",
    "Conversation",
    "ConversationManager",
    "ConversationSummary",
    "ConversationWithMessages",
    "Message",
    "MessageRole",
    "ReasoningTrace",
]
