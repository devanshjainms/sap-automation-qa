# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Function-level middleware: tool-call auditing and error recovery.
"""

from __future__ import annotations
import asyncio
import enum
import logging
import subprocess
import time
from collections.abc import Awaitable, Callable
from agent_framework import FunctionInvocationContext, FunctionMiddleware

logger = logging.getLogger(__name__)


class ErrorCategory(enum.Enum):
    """Category of a tool invocation error.

    :cvar TRANSIENT: Temporary failure — the agent may retry once.
    :cvar PERMANENT: The tool or resource does not exist — use alternative.
    :cvar DIAGNOSTIC: The error itself is useful evidence for triage.
    """

    TRANSIENT = "transient"
    PERMANENT = "permanent"
    DIAGNOSTIC = "diagnostic"


_TRANSIENT_TYPES: tuple[type[BaseException], ...] = (
    ConnectionResetError,
    ConnectionAbortedError,
    BrokenPipeError,
    TimeoutError,
    asyncio.TimeoutError,
    subprocess.TimeoutExpired,
)

_PERMANENT_TYPES: tuple[type[BaseException], ...] = (
    FileNotFoundError,
    PermissionError,
    NotImplementedError,
    ModuleNotFoundError,
    ImportError,
)


def _classify(exc: BaseException) -> ErrorCategory:
    """Classify an exception by its type hierarchy.

    :param exc: The caught exception.
    :returns: The error category.
    """
    if isinstance(exc, _TRANSIENT_TYPES):
        return ErrorCategory.TRANSIENT
    if isinstance(exc, _PERMANENT_TYPES):
        return ErrorCategory.PERMANENT
    return ErrorCategory.DIAGNOSTIC


_SCOPED_TOOLS: frozenset[str] = frozenset({"run_staf_test"})


class FunctionGuardMiddleware(FunctionMiddleware):
    """
    Intercepts every tool call for logging, scope enforcement,
    and error recovery.
    """

    def __init__(self) -> None:
        self._scoped_calls: dict[str, int] = {}

    _MESSAGES = {
        ErrorCategory.TRANSIENT: (
            "Timed out or lost connection. You may retry this tool call once, "
            "or try a different host / command."
        ),
        ErrorCategory.PERMANENT: (
            "This tool or resource is not available. " "Use a different approach or tool."
        ),
    }

    async def process(
        self,
        context: FunctionInvocationContext,
        call_next: Callable[[], Awaitable[None]],
    ) -> None:
        """Execute the tool call with logging and error handling.

        :param context: Framework-provided invocation context.
        :param call_next: Calls the next middleware or the tool itself.
        """
        name = context.function.name
        start = time.monotonic()

        if name in _SCOPED_TOOLS:
            self._scoped_calls[name] = self._scoped_calls.get(name, 0) + 1
            if self._scoped_calls[name] > 1:
                context.result = (
                    f"Tool '{name}' has already been called. "
                    "Ask the user which specific workspace to target "
                    "before running this tool on additional workspaces."
                )
                logger.warning(
                    "tool.scope_blocked  name=%s  calls=%d",
                    name,
                    self._scoped_calls[name],
                )
                return

        try:
            await call_next()
            elapsed = time.monotonic() - start
            logger.info(
                "tool.ok  name=%s  duration=%.2fs",
                name,
                elapsed,
            )
        except Exception as exc:
            elapsed = time.monotonic() - start
            category = _classify(exc)

            logger.log(
                logging.WARNING if category != ErrorCategory.DIAGNOSTIC else logging.ERROR,
                "tool.%s  name=%s  duration=%.2fs  error=%s: %s",
                category.value,
                name,
                elapsed,
                type(exc).__name__,
                str(exc)[:200],
                exc_info=(category == ErrorCategory.DIAGNOSTIC),
            )

            if category in self._MESSAGES:
                context.result = f"Tool '{name}' failed: {self._MESSAGES[category]}"
            else:
                short = str(exc)[:200]
                context.result = (
                    f"Tool '{name}' encountered an error: {short}. "
                    "This may be useful diagnostic information. "
                    "Try a different approach or tool."
                )
