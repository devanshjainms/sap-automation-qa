# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Semantic Kernel plugin for conversation memory management.

This plugin provides LLM-callable tools for explicitly storing and retrieving
facts during a conversation. Unlike the implicit ConversationContext managed
by the orchestrator, this plugin lets the LLM autonomously decide what to remember.

Design Philosophy:
- LLM explicitly controls what gets stored (not automatic extraction)
- Scoped per conversation (isolated between users/sessions)
- Simple key-value storage with optional categorization
- No persistence beyond conversation lifetime (ephemeral by design)

Use Cases:
- "Remember the SSH key path I discovered: /tmp/key.pem"
- "Recall the host IP I found earlier"
- "Store that this system uses SLES for future commands"
"""

from __future__ import annotations
import json
from datetime import datetime
from typing import Annotated, Optional, Dict, Any, TYPE_CHECKING
from semantic_kernel.functions import kernel_function
from src.agents.observability import get_logger

logger = get_logger(__name__)


class ConversationMemory:
    """Storage container for a single conversation's memories."""

    def __init__(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id
        self.memories: Dict[str, Dict[str, Any]] = {}
        self.created_at = datetime.utcnow()

    def store(self, key: str, value: str, category: Optional[str] = None) -> None:
        """Store a memory."""
        self.memories[key] = {
            "value": value,
            "category": category or "general",
            "stored_at": datetime.utcnow().isoformat(),
        }

    def retrieve(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve a memory by key."""
        return self.memories.get(key)

    def list_all(self) -> Dict[str, Dict[str, Any]]:
        """List all memories."""
        return self.memories

    def list_by_category(self, category: str) -> Dict[str, Dict[str, Any]]:
        """List memories in a specific category."""
        return {k: v for k, v in self.memories.items() if v.get("category") == category}

    def forget(self, key: str) -> bool:
        """Remove a memory."""
        if key in self.memories:
            del self.memories[key]
            return True
        return False


class MemoryPlugin:
    """Semantic Kernel plugin for explicit conversation memory.

    This plugin allows the LLM to autonomously store and retrieve facts
    discovered during a conversation. Unlike automatic context extraction,
    the LLM decides what's important enough to remember.

    Categories help organize memories:
    - "connection": SSH keys, hosts, credentials paths
    - "system": OS type, cluster type, capabilities discovered
    - "workspace": Workspace IDs, SIDs, paths
    - "execution": Test results, job IDs, status
    - "general": Anything else
    """

    def __init__(self) -> None:
        """Initialize MemoryPlugin with empty memory store."""
        self._memories: Dict[str, ConversationMemory] = {}
        logger.info("MemoryPlugin initialized")

    def _get_memory(self, conversation_id: str) -> ConversationMemory:
        """Get or create memory store for a conversation."""
        if conversation_id not in self._memories:
            self._memories[conversation_id] = ConversationMemory(conversation_id)
        return self._memories[conversation_id]

    @kernel_function(
        name="remember",
        description="Store a fact for later retrieval in this conversation. "
        "After executing commands/tests, store what you did (workspace, role, command, hosts) "
        "so you can answer follow-up questions like 'which node?' or 'what did you just run?'. "
        "Categories: 'execution' (commands/tests run), 'connection' (SSH keys, hosts), "
        "'system' (OS, cluster type), 'workspace' (SIDs, paths), 'general' (other).",
    )
    def remember(
        self,
        key: Annotated[str, "A short descriptive key (e.g., 'ssh_key_path', 'primary_db_host')"],
        value: Annotated[str, "The value to store (e.g., '/tmp/key.pem', '10.0.0.5')"],
        category: Annotated[
            str, "Category: 'connection', 'system', 'workspace', 'execution', or 'general'"
        ] = "general",
        conversation_id: Annotated[str, "Conversation ID (injected by system)"] = "",
    ) -> Annotated[str, "JSON confirmation of stored memory"]:
        """Store a fact in conversation memory.

        :param key: Short descriptive key for the fact
        :type key: str
        :param value: The value to store
        :type value: str
        :param category: Category for organization
        :type category: str
        :param conversation_id: Conversation ID (injected)
        :type conversation_id: str
        :returns: JSON confirmation
        :rtype: str
        """
        memory = self._get_memory(conversation_id or "_default_")
        memory.store(key, value, category)

        logger.info(f"Memory stored: {key}={value[:50]}... (category={category})")

        return json.dumps(
            {
                "stored": True,
                "key": key,
                "category": category,
                "message": f"Remembered '{key}' for this conversation",
            }
        )

    @kernel_function(
        name="recall",
        description="Retrieve a previously stored fact by its key. "
        "Use this to answer follow-up questions about previous actions "
        "(e.g., 'which node?', 'what did you run?') by recalling execution details.",
    )
    def recall(
        self,
        key: Annotated[str, "The key to look up (e.g., 'ssh_key_path')"],
        conversation_id: Annotated[str, "Conversation ID (injected by system)"] = "",
    ) -> Annotated[str, "JSON with the retrieved value or error"]:
        """Retrieve a fact from conversation memory.

        :param key: Key to look up
        :type key: str
        :param conversation_id: Conversation ID (injected)
        :type conversation_id: str
        :returns: JSON with value or error
        :rtype: str
        """
        memory = self._get_memory(conversation_id or "_default_")
        result = memory.retrieve(key)

        if result:
            logger.info(f"Memory recalled: {key}")
            return json.dumps(
                {
                    "found": True,
                    "key": key,
                    "value": result["value"],
                    "category": result["category"],
                    "stored_at": result["stored_at"],
                }
            )
        else:
            return json.dumps(
                {
                    "found": False,
                    "key": key,
                    "message": f"No memory found for '{key}'",
                }
            )

    @kernel_function(
        name="list_memories",
        description="List all facts stored in this conversation, optionally filtered by category.",
    )
    def list_memories(
        self,
        category: Annotated[
            str,
            "Optional category filter ('connection', 'system', 'workspace', 'execution', 'general', or empty for all)",
        ] = "",
        conversation_id: Annotated[str, "Conversation ID (injected by system)"] = "",
    ) -> Annotated[str, "JSON with all stored memories"]:
        """List all stored memories.

        :param category: Optional category filter
        :type category: str
        :param conversation_id: Conversation ID (injected)
        :type conversation_id: str
        :returns: JSON with memories
        :rtype: str
        """
        memory = self._get_memory(conversation_id or "_default_")

        if category:
            memories = memory.list_by_category(category)
        else:
            memories = memory.list_all()
        formatted = []
        for key, data in memories.items():
            formatted.append(
                {
                    "key": key,
                    "value": data["value"],
                    "category": data["category"],
                }
            )

        return json.dumps(
            {
                "memories": formatted,
                "count": len(formatted),
                "filter": category if category else "all",
            },
            indent=2,
        )

    @kernel_function(
        name="forget",
        description="Remove a stored fact from memory. Use when information is no longer relevant.",
    )
    def forget(
        self,
        key: Annotated[str, "The key to forget"],
        conversation_id: Annotated[str, "Conversation ID (injected by system)"] = "",
    ) -> Annotated[str, "JSON confirmation"]:
        """Remove a fact from memory.

        :param key: Key to remove
        :type key: str
        :param conversation_id: Conversation ID (injected)
        :type conversation_id: str
        :returns: JSON confirmation
        :rtype: str
        """
        memory = self._get_memory(conversation_id or "_default_")
        removed = memory.forget(key)

        if removed:
            logger.info(f"Memory forgotten: {key}")
            return json.dumps({"forgotten": True, "key": key})
        else:
            return json.dumps(
                {"forgotten": False, "key": key, "message": f"No memory found for '{key}'"}
            )

    def clear_conversation(self, conversation_id: str) -> None:
        """Clear all memories for a conversation (called by orchestrator on cleanup).

        :param conversation_id: Conversation ID to clear
        :type conversation_id: str
        """
        if conversation_id in self._memories:
            del self._memories[conversation_id]
            logger.info(f"Cleared memories for conversation {conversation_id}")
