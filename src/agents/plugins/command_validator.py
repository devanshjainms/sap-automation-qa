# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Command validation for read-only operations.

This module provides strict validation for shell commands to ensure
only safe, read-only operations are executed via ad-hoc Ansible.
"""

import shlex
from typing import Tuple

from src.agents.constants import (
    ALLOWED_BINARIES,
    FORBIDDEN_TOKENS,
    SAFE_PATH_PREFIXES,
)
from src.agents.logging_config import get_logger

logger = get_logger(__name__)

# Re-export constants for backward compatibility
__all__ = [
    "ALLOWED_BINARIES",
    "FORBIDDEN_TOKENS",
    "SAFE_PATH_PREFIXES",
    "validate_readonly_command",
    "validate_command_safe",
]


def validate_readonly_command(command: str) -> None:
    """Validate that a command is safe and read-only.

    This function implements strict validation to prevent:
    - State mutation (file writes, deletions, modifications)
    - Privilege escalation
    - Package installation
    - Process termination
    - System configuration changes
    - Arbitrary code execution

    :param command: Shell command string to validate
    :type command: str
    :raises ValueError: If command is not allowed with explanation
    """
    if not command or not command.strip():
        raise ValueError("Empty command not allowed")

    command = command.strip()

    dangerous_operators = [";", "&&", "||", "`", "$(", "$("]
    for op in dangerous_operators:
        if op in command:
            raise ValueError(
                f"Command contains forbidden shell operator '{op}'. "
                "Shell control operators are not allowed for safety."
            )
    try:
        tokens = shlex.split(command)
    except ValueError as e:
        raise ValueError(f"Invalid command syntax: {e}")

    if not tokens:
        raise ValueError("No tokens found in command")
    if "|" in command:
        segments = command.split("|")
        for segment in segments:
            segment = segment.strip()
            if segment:
                validate_readonly_command(segment)
        return
    binary = tokens[0]
    if "/" in binary:
        binary = binary.split("/")[-1]

    if binary not in ALLOWED_BINARIES:
        raise ValueError(
            f"Binary '{binary}' is not in the allowed list. "
            f"Allowed binaries: {', '.join(sorted(ALLOWED_BINARIES))}"
        )
    for token in tokens:
        token_lower = token.lower()
        if token_lower in FORBIDDEN_TOKENS:
            raise ValueError(
                f"Token '{token}' is a forbidden operation. "
                "This operation is not allowed."
            )
        if "/" not in token and "." not in token:
            for forbidden in FORBIDDEN_TOKENS:
                if token_lower == forbidden:
                    raise ValueError(
                        f"Token '{token}' is forbidden. "
                        "This operation is not allowed."
                    )

    if binary == "sysctl":
        if any(token in ["-w", "--write"] for token in tokens):
            raise ValueError(
                "sysctl with -w/--write is not allowed. Use read-only sysctl commands."
            )

    for token in tokens[1:]:
        if token.startswith("/"):
            is_safe = any(token.startswith(prefix) for prefix in SAFE_PATH_PREFIXES)
            if not is_safe:
                logger.warning(
                    f"Path '{token}' does not start with a known safe prefix. "
                    f"Safe prefixes: {SAFE_PATH_PREFIXES}"
                )

    logger.info(f"Command validated as read-only: {command}")


def validate_command_safe(command: str) -> Tuple[bool, str]:
    """Validate command and return result as tuple instead of raising.

    This is a wrapper around validate_readonly_command that returns
    a tuple (is_valid, reason) instead of raising exceptions.

    :param command: Shell command string to validate
    :type command: str
    :returns: Tuple of (is_valid, reason)
    :rtype: Tuple[bool, str]
    """
    try:
        validate_readonly_command(command)
        return True, "Command validated as safe"
    except ValueError as e:
        return False, str(e)
