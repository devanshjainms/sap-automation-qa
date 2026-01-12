# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Request-scoped context for plugins.

This module provides a thread-safe way to pass request context (conversation_id,
user_id, etc.) to plugins during agent invocation. This solves the problem of
Semantic Kernel not having built-in support for injecting request context into
kernel function parameters.

"""

from contextvars import ContextVar
from typing import Optional, Any
from src.agents.observability import get_logger
from src.agents.models.context import RequestContextData

logger = get_logger(__name__)
_request_context: ContextVar[Optional[RequestContextData]] = ContextVar(
    "request_context", default=None
)


class RequestContext:
    """Static interface for accessing request-scoped context.

    This class provides a thread-safe way to pass request context to plugins
    without requiring parameter injection. Uses Python's contextvars for
    proper isolation between concurrent requests.

    Example:
        # At request start (in orchestrator):
        RequestContext.set(conversation_id="abc-123", user_id="user@example.com")

        # In any plugin method:
        conv_id = RequestContext.get_conversation_id()  # Returns "abc-123"

        # At request end:
        RequestContext.clear()
    """

    @classmethod
    def set(
        cls,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        sid: Optional[str] = None,
        **metadata: Any,
    ) -> None:
        """Set the request context for the current execution context.

        :param conversation_id: Conversation ID for this request
        :type conversation_id: Optional[str]
        :param user_id: User ID making the request
        :type user_id: Optional[str]
        :param correlation_id: Correlation ID for distributed tracing
        :type correlation_id: Optional[str]
        :param workspace_id: Active workspace ID
        :type workspace_id: Optional[str]
        :param sid: SAP System ID
        :type sid: Optional[str]
        :param metadata: Additional context data
        :type metadata: Any
        """
        ctx = RequestContextData(
            conversation_id=conversation_id,
            user_id=user_id,
            correlation_id=correlation_id,
            workspace_id=workspace_id,
            sid=sid,
            metadata=dict(metadata),
        )
        _request_context.set(ctx)
        logger.debug(
            f"RequestContext set: conversation_id={conversation_id}, "
            f"workspace_id={workspace_id}, sid={sid}"
        )

    @classmethod
    def get(cls) -> Optional[RequestContextData]:
        """Get the current request context.

        :returns: Current RequestContextData or None if not set
        :rtype: Optional[RequestContextData]
        """
        return _request_context.get()

    @classmethod
    def get_conversation_id(cls) -> Optional[str]:
        """Get the current conversation ID.

        :returns: Conversation ID or None
        :rtype: Optional[str]
        """
        ctx = cls.get()
        return ctx.conversation_id if ctx else None

    @classmethod
    def get_workspace_id(cls) -> Optional[str]:
        """Get the current workspace ID.

        :returns: Workspace ID or None
        :rtype: Optional[str]
        """
        ctx = cls.get()
        return ctx.workspace_id if ctx else None

    @classmethod
    def get_sid(cls) -> Optional[str]:
        """Get the current SAP System ID.

        :returns: SID or None
        :rtype: Optional[str]
        """
        ctx = cls.get()
        return ctx.sid if ctx else None

    @classmethod
    def get_user_id(cls) -> Optional[str]:
        """Get the current user ID.

        :returns: User ID or None
        :rtype: Optional[str]
        """
        ctx = cls.get()
        return ctx.user_id if ctx else None

    @classmethod
    def get_correlation_id(cls) -> Optional[str]:
        """Get the current correlation ID for tracing.

        :returns: Correlation ID or None
        :rtype: Optional[str]
        """
        ctx = cls.get()
        return ctx.correlation_id if ctx else None

    @classmethod
    def update(cls, **kwargs: Any) -> None:
        """Update specific fields in the current context.

        :param kwargs: Fields to update
        :type kwargs: Any
        """
        ctx = cls.get()
        if ctx:
            for key, value in kwargs.items():
                if hasattr(ctx, key):
                    setattr(ctx, key, value)
                else:
                    ctx.metadata[key] = value
            logger.debug(f"RequestContext updated: {list(kwargs.keys())}")
        else:
            logger.warning("Cannot update RequestContext: not set")

    @classmethod
    def clear(cls) -> None:
        """Clear the request context.

        Should be called at the end of each request to prevent memory leaks
        and context pollution between requests.
        """
        _request_context.set(None)
        logger.debug("RequestContext cleared")
