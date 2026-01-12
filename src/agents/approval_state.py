# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Conversation-scoped approval state to prevent confirmation loops.

This module tracks user approvals within a conversation to avoid
asking for permission repeatedly for the same actions.
"""

from contextvars import ContextVar
from typing import Optional, Set
from dataclasses import dataclass, field

from src.agents.observability import get_logger

logger = get_logger(__name__)
_approval_state: ContextVar[Optional["ApprovalState"]] = ContextVar("approval_state", default=None)


@dataclass
class ApprovalState:
    """Tracks approved actions within a conversation.

    Prevents agents from asking for permission multiple times
    for the same command or action pattern.
    """

    conversation_id: str
    approved_commands: Set[str] = field(default_factory=set)
    approved_patterns: Set[str] = field(default_factory=set)

    def approve_command(self, command: str) -> None:
        """Mark a specific command as approved.

        :param command: Exact command string
        """
        self.approved_commands.add(command)
        logger.info(f"Command approved in conversation {self.conversation_id}: {command}")

    def approve_pattern(self, pattern: str) -> None:
        """Mark a command pattern as approved.

        Patterns are higher-level categories like:
        - "diagnostic_commands" (crm status, systemctl status, etc.)
        - "read_logs" (tail, cat log files)
        - "cluster_info" (cluster info queries)

        :param pattern: Pattern identifier
        """
        self.approved_patterns.add(pattern)
        logger.info(f"Pattern approved in conversation {self.conversation_id}: {pattern}")

    def is_command_approved(self, command: str) -> bool:
        """Check if specific command is approved.

        :param command: Command to check
        :returns: True if previously approved
        """
        return command in self.approved_commands

    def is_pattern_approved(self, pattern: str) -> bool:
        """Check if command pattern is approved.

        :param pattern: Pattern to check
        :returns: True if previously approved
        """
        return pattern in self.approved_patterns


class ApprovalStateManager:
    """Manages approval state for conversations."""

    @staticmethod
    def set(state: ApprovalState) -> None:
        """Set approval state for current context.

        :param state: ApprovalState instance
        """
        _approval_state.set(state)

    @staticmethod
    def get() -> Optional[ApprovalState]:
        """Get current approval state.

        :returns: ApprovalState if set, None otherwise
        """
        return _approval_state.get()

    @staticmethod
    def clear() -> None:
        """Clear approval state for current context."""
        _approval_state.set(None)

    @staticmethod
    def get_or_create(conversation_id: str) -> ApprovalState:
        """Get existing approval state or create new one.

        :param conversation_id: Conversation ID
        :returns: ApprovalState instance
        """
        state = _approval_state.get()
        if state and state.conversation_id == conversation_id:
            return state

        new_state = ApprovalState(conversation_id=conversation_id)
        _approval_state.set(new_state)
        logger.info(f"Created new approval state for conversation {conversation_id}")
        return new_state
