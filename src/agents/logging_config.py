# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Centralized logging configuration with request-scoped correlation IDs.

This module provides a unified logging setup for all agents with support for
tracking individual requests via correlation IDs (GUIDs). The correlation ID
is maintained per request using contextvars for thread-safe operation in async
environments.
"""

import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Optional

correlation_id_var: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


class CorrelationIdFilter(logging.Filter):
    """
    Logging filter that adds correlation_id to log records.

    :param name: Filter name
    :type name: str
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Add correlation_id to the log record.

        :param record: Log record to filter
        :type record: logging.LogRecord
        :returns: Always True to include all records
        :rtype: bool
        """
        record.correlation_id = correlation_id_var.get() or "no-correlation-id"
        return True


def initialize_logging(level: int = logging.INFO) -> None:
    """Initialize logging configuration for the entire agents module.

    Sets up a centralized logger with correlation ID support. Should be called
    once at application startup.

    :param level: Logging level (default: logging.INFO)
    :type level: int
    """
    root_logger = logging.getLogger("src.agents")
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s - [%(correlation_id)s] - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    console_handler.addFilter(CorrelationIdFilter())
    root_logger.addHandler(console_handler)
    root_logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for a module.

    :param name: Module name (typically __name__)
    :type name: str
    :returns: Configured logger instance
    :rtype: logging.Logger
    """
    return logging.getLogger(name)


def set_correlation_id(correlation_id: Optional[str] = None) -> str:
    """Set correlation ID for the current request context.

    :param correlation_id: Optional correlation ID (generates UUID if not provided)
    :type correlation_id: Optional[str]
    :returns: The correlation ID that was set
    :rtype: str
    """
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())
    correlation_id_var.set(correlation_id)
    return correlation_id


def get_correlation_id() -> Optional[str]:
    """Get the current correlation ID from context.

    :returns: Current correlation ID or None
    :rtype: Optional[str]
    """
    return correlation_id_var.get()


def clear_correlation_id() -> None:
    """Clear the correlation ID from current context."""
    correlation_id_var.set(None)
