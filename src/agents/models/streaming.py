# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Streaming event models for real-time thinking/reasoning display.

These models support ChatGPT-style streaming where users see the AI's
thinking process as it happens.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine, Literal, Optional
from uuid import uuid4
from contextvars import ContextVar

from pydantic import BaseModel, Field


class StreamEventType(str, Enum):
    """Types of streaming events."""

    THINKING_START = "thinking_start"
    THINKING_STEP = "thinking_step"
    THINKING_END = "thinking_end"
    CONTENT_DELTA = "content_delta"
    CONTENT_DONE = "content_done"
    ERROR = "error"
    DONE = "done"


class ThinkingStep(BaseModel):
    """A single thinking step to display to the user."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    agent: str = Field(..., description="Agent performing this step")
    action: str = Field(..., description="Short action description for UI")
    detail: Optional[str] = Field(None, description="Optional detail text")
    status: Literal["pending", "in_progress", "complete", "error"] = Field(default="in_progress")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    duration_ms: Optional[int] = Field(None, description="Duration if complete")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class StreamEvent(BaseModel):
    """A streaming event to send to the frontend."""

    type: StreamEventType
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}

    @classmethod
    def thinking_start(cls) -> "StreamEvent":
        """Create a thinking_start event."""
        return cls(type=StreamEventType.THINKING_START)

    @classmethod
    def thinking_step(
        cls,
        agent: str,
        action: str,
        detail: Optional[str] = None,
        status: Literal["pending", "in_progress", "complete", "error"] = "in_progress",
        step_id: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> "StreamEvent":
        """Create a thinking_step event."""
        step = ThinkingStep(
            id=step_id or str(uuid4()),
            agent=agent,
            action=action,
            detail=detail,
            status=status,
            duration_ms=duration_ms,
        )
        return cls(
            type=StreamEventType.THINKING_STEP,
            data={"step": step.model_dump(mode="json")},
        )

    @classmethod
    def thinking_end(cls) -> "StreamEvent":
        """Create a thinking_end event."""
        return cls(type=StreamEventType.THINKING_END)

    @classmethod
    def content_delta(cls, content: str) -> "StreamEvent":
        """Create a content_delta event for streaming text."""
        return cls(
            type=StreamEventType.CONTENT_DELTA,
            data={"content": content},
        )

    @classmethod
    def content_done(cls, full_content: str) -> "StreamEvent":
        """Create a content_done event with full response."""
        return cls(
            type=StreamEventType.CONTENT_DONE,
            data={"content": full_content},
        )

    @classmethod
    def error(cls, message: str, code: Optional[str] = None) -> "StreamEvent":
        """Create an error event."""
        return cls(
            type=StreamEventType.ERROR,
            data={"message": message, "code": code},
        )

    @classmethod
    def done(cls, reasoning_trace: Optional[dict] = None) -> "StreamEvent":
        """Create a done event with optional reasoning trace."""
        return cls(
            type=StreamEventType.DONE,
            data={"reasoning_trace": reasoning_trace},
        )


StreamCallback = Callable[[StreamEvent], Coroutine[Any, Any, None]]

_stream_callback: ContextVar[Optional[StreamCallback]] = ContextVar(
    "_stream_callback", default=None
)


def set_stream_callback(callback: Optional[StreamCallback]) -> None:
    """Set the current stream callback for emitting events.

    :param callback: Async callback to receive stream events
    """
    _stream_callback.set(callback)


def get_stream_callback() -> Optional[StreamCallback]:
    """Get the current stream callback.

    :returns: Current stream callback or None
    """
    return _stream_callback.get()


async def emit_thinking_step(
    agent: str,
    action: str,
    detail: Optional[str] = None,
    status: Literal["pending", "in_progress", "complete", "error"] = "in_progress",
    step_id: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> Optional[str]:
    """Emit a thinking step if a stream callback is set.

    :param agent: Agent name
    :param action: Action description
    :param detail: Optional detail
    :param status: Step status
    :param step_id: Optional step ID for updates
    :param duration_ms: Duration if complete
    :returns: Step ID for later updates, or None if no callback
    """
    callback = get_stream_callback()
    if callback:
        event = StreamEvent.thinking_step(
            agent=agent,
            action=action,
            detail=detail,
            status=status,
            step_id=step_id,
            duration_ms=duration_ms,
        )
        await callback(event)
        return event.data["step"]["id"]
    return None


async def emit_thinking_start() -> None:
    """Emit thinking_start event if callback is set."""
    callback = get_stream_callback()
    if callback:
        await callback(StreamEvent.thinking_start())


async def emit_thinking_end() -> None:
    """Emit thinking_end event if callback is set."""
    callback = get_stream_callback()
    if callback:
        await callback(StreamEvent.thinking_end())


async def emit_content_delta(content: str) -> None:
    """Emit content_delta event if callback is set."""
    callback = get_stream_callback()
    if callback:
        await callback(StreamEvent.content_delta(content))
