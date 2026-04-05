# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Agent-level middleware: top-level exception handling.
"""

from __future__ import annotations
import logging
from collections.abc import Awaitable, Callable
from agent_framework import AgentContext, AgentMiddleware, AgentResponse, Message

logger = logging.getLogger(__name__)


class AgentExceptionMiddleware(AgentMiddleware):
    """
    Wraps the full agent run to catch unhandled exceptions.
    """

    _USER_MESSAGE = (
        "I'm sorry, I ran into an unexpected problem while processing "
        "your request. Please try again — by providing some more context"
    )

    async def process(
        self,
        context: AgentContext,
        call_next: Callable[[], Awaitable[None]],
    ) -> None:
        """Execute the agent run with top-level error handling.

        :param context: Framework-provided agent context.
        :param call_next: Calls the next middleware or agent execution.
        """
        try:
            await call_next()
        except Exception as exc:
            logger.error(
                "agent.unhandled_error  error=%s: %s",
                type(exc).__name__,
                str(exc)[:300],
                exc_info=True,
            )
            context.result = AgentResponse(
                messages=[
                    Message("assistant", text=self._USER_MESSAGE),
                ],
            )
