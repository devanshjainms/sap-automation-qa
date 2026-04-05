# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Agent Framework middleware package.

Re-exports all middleware classes and the error-classification helper
so existing ``from src.agents.providers.middleware import …`` imports
continue to work unchanged.

Middleware layers (outer → inner):

1. **AgentExceptionMiddleware** — wraps the entire agent run.
2. **InvestigationChatMiddleware** — wraps each LLM round-trip.
3. **OutputSanitizationMiddleware** — sanitizes tool output.
4. **FunctionGuardMiddleware** — wraps each tool invocation.
"""

from src.agents.providers.middleware.chat_middleware import (
    InvestigationChatMiddleware,
)
from src.agents.providers.middleware.exception_middleware import (
    AgentExceptionMiddleware,
)
from src.agents.providers.middleware.function_middleware import (
    ErrorCategory,
    FunctionGuardMiddleware,
    _classify,
)
from src.agents.providers.middleware.sanitizer import (
    OutputSanitizationMiddleware,
)

__all__ = [
    "AgentExceptionMiddleware",
    "ErrorCategory",
    "FunctionGuardMiddleware",
    "InvestigationChatMiddleware",
    "OutputSanitizationMiddleware",
    "_classify",
]
