# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Structured logging with OOP design.

This module provides:
- LogFormatter: Abstract base for log formatters (JSON, Console)
- StructuredLogger: Logger wrapper with context injection and event support
- LoggerFactory: Factory for creating configured loggers

Design patterns used:
- Factory: LoggerFactory creates configured loggers
- Strategy: Formatters implement different output strategies
- Adapter: StructuredLogger adapts stdlib logging
"""

from __future__ import annotations

import json
import logging
import os
import sys
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional, Union

from src.agents.observability.context import ObservabilityContextManager
from src.agents.observability.events import (
    ServiceEvent,
    AgentEvent,
    ExecutionEvent,
)


class LogFormatter(ABC, logging.Formatter):
    """
    Abstract base class for log formatters.

    Implements Strategy pattern - different formatters provide
    different output formats while sharing the same interface.
    """

    def __init__(self, service_name: str = "sap-qa-agents") -> None:
        """Initialize formatter.

        :param service_name: Service name to include in logs
        :type service_name: str
        """
        super().__init__()
        self.service_name = service_name
        self._context_manager = ObservabilityContextManager.instance()

    @abstractmethod
    def format(self, record: logging.LogRecord) -> str:
        """Format log record to string.

        :param record: Log record to format
        :type record: logging.LogRecord
        :returns: Formatted log string
        :rtype: str
        """
        pass

    def _get_context_dict(self) -> dict[str, Any]:
        """Get current context as dict for inclusion in logs.

        :returns: Context dictionary
        :rtype: dict[str, Any]
        """
        ctx = self._context_manager
        result: dict[str, Any] = {}

        if ctx.correlation_id:
            result["correlation_id"] = ctx.correlation_id
        if ctx.conversation_id:
            result["conversation_id"] = ctx.conversation_id
        if ctx.agent_invocation_id:
            result["agent_invocation_id"] = ctx.agent_invocation_id
        if ctx.agent_name:
            result["agent_name"] = ctx.agent_name
        if ctx.workspace_id:
            result["workspace_id"] = ctx.workspace_id
        if ctx.execution_id:
            result["execution_id"] = ctx.execution_id

        return result

    def _get_extra_fields(self, record: logging.LogRecord) -> dict[str, Any]:
        """Extract extra fields from log record.

        :param record: Log record
        :type record: logging.LogRecord
        :returns: Extra fields dictionary
        :rtype: dict[str, Any]
        """
        standard_attrs = {
            "name",
            "msg",
            "args",
            "created",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "exc_info",
            "exc_text",
            "thread",
            "threadName",
            "message",
            "taskName",
        }

        extra: dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key not in standard_attrs and not key.startswith("_"):
                extra[key] = value
        return extra


class JSONFormatter(LogFormatter):
    """
    JSON log formatter for production use.

    Outputs single-line JSON compatible with:
    - Loki
    - Fluentd
    - Elasticsearch
    - Azure Log Analytics
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON.

        :param record: Log record
        :type record: logging.LogRecord
        :returns: JSON-formatted log line
        :rtype: str
        """
        log_dict: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service_name,
        }

        log_dict.update(self._get_context_dict())
        log_dict.update(self._get_extra_fields(record))
        if record.exc_info:
            log_dict["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_dict, default=str, ensure_ascii=False)


class ConsoleFormatter(LogFormatter):
    """
    Human-readable console formatter for development.

    Color-coded output with truncated correlation ID for readability.
    """

    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "WARN": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
        "RESET": "\033[0m",
    }

    def format(self, record: logging.LogRecord) -> str:
        """Format log record for console.

        :param record: Log record
        :type record: logging.LogRecord
        :returns: Formatted log line
        :rtype: str
        """
        ctx = self._context_manager
        corr_id = ctx.correlation_id or "-"
        short_corr = corr_id[:8] if corr_id != "-" else "-"
        color = self.COLORS.get(record.levelname, "")
        reset = self.COLORS["RESET"]
        agent_prefix = f"[{ctx.agent_name}] " if ctx.agent_name else ""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        formatted = (
            f"{timestamp} [{short_corr}] {agent_prefix}"
            f"{color}{record.levelname:5}{reset} "
            f"{record.name.split('.')[-1]} - {record.getMessage()}"
        )
        extras = []
        extra_fields = self._get_extra_fields(record)
        for key in ("event", "duration_ms", "status", "error"):
            if key in extra_fields:
                extras.append(f"{key}={extra_fields[key]}")

        if extras:
            formatted += f" ({', '.join(extras)})"

        return formatted


class StructuredLogger:
    """
    Structured logger with context injection and event support.

    Wraps stdlib logging.Logger to provide:
    - Automatic context injection
    - Typed event logging
    - Extra field support

    Usage:
        logger = StructuredLogger("my.module")
        logger.info("Processing", event="request_start", count=5)
        logger.event(create_agent_event("agent_start"))
    """

    def __init__(self, name: str) -> None:
        """Initialize structured logger.

        :param name: Logger name (typically __name__)
        :type name: str
        """
        self._logger = logging.getLogger(name)
        self.name = name

    def _log(
        self,
        level: int,
        msg: str,
        *args,
        exc_info: Optional[Exception] = None,
        **kwargs,
    ) -> None:
        """Internal log method.

        :param level: Log level
        :param msg: Message
        :param args: Format args
        :param exc_info: Exception info
        :param kwargs: Extra fields
        """
        self._logger.log(level, msg, *args, exc_info=exc_info, extra=kwargs)

    def debug(self, msg: str, *args, **kwargs) -> None:
        """Log debug message."""
        self._log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs) -> None:
        """Log info message."""
        self._log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs) -> None:
        """Log warning message."""
        self._log(logging.WARNING, msg, *args, **kwargs)

    def warn(self, msg: str, *args, **kwargs) -> None:
        """Log warning (alias)."""
        self.warning(msg, *args, **kwargs)

    def error(
        self,
        msg: str,
        *args,
        exc_info: Optional[Exception] = None,
        **kwargs,
    ) -> None:
        """Log error message."""
        self._log(logging.ERROR, msg, *args, exc_info=exc_info, **kwargs)

    def exception(self, msg: str, *args, **kwargs) -> None:
        """Log exception with traceback."""
        self._logger.exception(msg, *args, extra=kwargs)

    def event(
        self,
        event: Union[ServiceEvent, AgentEvent, ExecutionEvent],
    ) -> None:
        """Log a typed event.

        :param event: Event instance
        :type event: Union[ServiceEvent, AgentEvent, ExecutionEvent]
        """
        level_str = event.level.value if hasattr(event.level, "value") else str(event.level)
        level = getattr(logging, level_str)
        stream_str = event.stream.value if hasattr(event.stream, "value") else str(event.stream)
        event_dict = event.model_dump(exclude_none=True, mode="json")
        msg = f"[{stream_str}] {event.event}"
        for key in ("timestamp", "level", "stream"):
            event_dict.pop(key, None)

        self._logger.log(level, msg, extra=event_dict)

    def setLevel(self, level: int) -> None:
        """Set logger level."""
        self._logger.setLevel(level)

    @property
    def level(self) -> int:
        """Get effective log level."""
        return self._logger.getEffectiveLevel()


class LoggerFactory:
    """
    Factory for creating and configuring loggers.

    Implements Singleton pattern for global configuration.
    """

    _initialized: bool = False
    _format: str = "json"
    _level: int = logging.INFO
    _service_name: str = "sap-qa-agents"

    @classmethod
    def initialize(
        cls,
        level: int = logging.INFO,
        log_format: str = "json",
        service_name: str = "sap-qa-agents",
    ) -> None:
        """Initialize logging configuration.

        Call once at application startup.

        :param level: Log level
        :type level: int
        :param log_format: Format type - "json" or "console"
        :type log_format: str
        :param service_name: Service name for logs
        :type service_name: str
        """
        if cls._initialized:
            return

        cls._format = log_format
        cls._level = level
        cls._service_name = service_name
        cls._configure_logger("src.agents", level, log_format, service_name)
        cls._configure_logger("src.api", level, log_format, service_name)

        cls._initialized = True

    @classmethod
    def _configure_logger(
        cls,
        name: str,
        level: int,
        log_format: str,
        service_name: str,
    ) -> None:
        """Configure a logger with formatter.

        :param name: Logger name
        :param level: Log level
        :param log_format: Format type
        :param service_name: Service name
        """
        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.handlers.clear()

        # Console handler (stdout)
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)

        if log_format == "json":
            handler.setFormatter(JSONFormatter(service_name=service_name))
        else:
            handler.setFormatter(ConsoleFormatter(service_name=service_name))

        logger.addHandler(handler)

        # File handler - always JSON for easy parsing
        log_dir = Path(os.environ.get("LOG_DIR", "data/logs"))
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "sap-qa-agents.log"

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(JSONFormatter(service_name=service_name))
        logger.addHandler(file_handler)

        logger.propagate = False

    @classmethod
    def get_logger(cls, name: str) -> StructuredLogger:
        """Get a structured logger instance.

        :param name: Logger name (typically __name__)
        :type name: str
        :returns: StructuredLogger instance
        :rtype: StructuredLogger
        """
        return StructuredLogger(name)

    @classmethod
    def reset(cls) -> None:
        """Reset factory state (for testing)."""
        cls._initialized = False
        cls._format = "json"
        cls._level = logging.INFO


def initialize_logging(
    level: int = logging.INFO,
    log_format: str = "json",
    service_name: str = "sap-qa-agents",
) -> None:
    """Initialize logging. Call once at startup.

    :param level: Log level
    :param log_format: "json" or "console"
    :param service_name: Service name for logs
    """
    LoggerFactory.initialize(level=level, log_format=log_format, service_name=service_name)


def get_logger(name: str) -> StructuredLogger:
    """Get a structured logger.

    :param name: Logger name (typically __name__)
    :returns: StructuredLogger instance
    """
    return LoggerFactory.get_logger(name)


def clear_correlation_id() -> None:
    """Clear correlation ID from context."""
    from src.agents.observability.context import clear_context

    clear_context()
