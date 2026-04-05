# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Output sanitization middleware — truncates oversized tool results
and strips potential prompt-injection markers.

Sits in the function middleware pipeline alongside
:class:`FunctionGuardMiddleware` and processes the *result* after
the tool has run.
"""

from __future__ import annotations
import logging
import re
from collections.abc import Awaitable, Callable
from agent_framework import FunctionInvocationContext, FunctionMiddleware

logger = logging.getLogger(__name__)

_DEFAULT_MAX_CHARS = 30_000

_INJECTION_PATTERNS = re.compile(
    r"(IGNORE PREVIOUS INSTRUCTIONS"
    r"|SYSTEM PROMPT OVERRIDE"
    r"|<\|im_start\|>system"
    r"|<\|endoftext\|>"
    r"|<<SYS>>)",
    re.IGNORECASE,
)


class OutputSanitizationMiddleware(FunctionMiddleware):
    """Truncates oversized tool output and strips injection patterns.

    :param max_chars: Maximum allowed characters in a tool result.
        Results exceeding this are truncated with a notice.
    """

    def __init__(self, *, max_chars: int = _DEFAULT_MAX_CHARS) -> None:
        self._max_chars = max_chars

    async def process(
        self,
        context: FunctionInvocationContext,
        call_next: Callable[[], Awaitable[None]],
    ) -> None:
        """Execute the tool call, then sanitize the result.

        :param context: Framework-provided invocation context.
        :param call_next: Calls the next middleware or the tool itself.
        """
        await call_next()

        result = context.result
        if not isinstance(result, str):
            return

        sanitized = self._strip_injection(result)
        sanitized = self._truncate(sanitized)

        if sanitized != result:
            context.result = sanitized

    def _truncate(self, text: str) -> str:
        """Truncate text to ``max_chars`` with a trailing notice.

        :param text: Raw tool output.
        :returns: Possibly truncated text.
        """
        if len(text) <= self._max_chars:
            return text
        logger.info(
            "Truncating tool output from %d to %d chars",
            len(text),
            self._max_chars,
        )
        return (
            text[: self._max_chars]
            + "\n\n[Output truncated — "
            + f"{len(text) - self._max_chars} chars omitted]"
        )

    @staticmethod
    def _strip_injection(text: str) -> str:
        """Remove known prompt-injection markers.

        :param text: Raw tool output.
        :returns: Cleaned text.
        """
        cleaned = _INJECTION_PATTERNS.sub("[REDACTED]", text)
        if cleaned != text:
            logger.warning("Stripped potential injection pattern from tool output")
        return cleaned
