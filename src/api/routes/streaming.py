# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Server-Sent Events (SSE) streaming for real-time updates.

This module provides SSE streaming capabilities for:
- Chat response streaming
- Job execution progress updates
"""

import asyncio
import json
from typing import Any, AsyncGenerator, Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from src.agents.execution.worker import JobWorker, JobEventEmitter
from src.agents.observability import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["streaming"])

_job_worker: Optional[JobWorker] = None


def set_job_worker(worker: JobWorker) -> None:
    """Set the global job worker instance.

    :param worker: JobWorker instance
    :type worker: JobWorker
    """
    global _job_worker
    _job_worker = worker


def get_job_worker() -> Optional[JobWorker]:
    """Get the global job worker instance.

    :returns: JobWorker instance or None
    :rtype: Optional[JobWorker]
    """
    return _job_worker


async def format_sse_event(
    data: dict[str, Any],
    event: Optional[str] = None,
    id: Optional[str] = None,
) -> str:
    """Format data as an SSE event.

    :param data: Data to send
    :type data: dict[str, Any]
    :param event: Optional event name
    :type event: Optional[str]
    :param id: Optional event ID
    :type id: Optional[str]
    :returns: Formatted SSE string
    :rtype: str
    """
    lines = []
    if id:
        lines.append(f"id: {id}")
    if event:
        lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data)}")
    lines.append("")
    return "\n".join(lines) + "\n"


async def job_event_stream(
    job_id: str,
    timeout: float = 300.0,
) -> AsyncGenerator[str, None]:
    """Generate SSE events for a job.

    :param job_id: Job ID to stream events for
    :type job_id: str
    :param timeout: Stream timeout in seconds
    :type timeout: float
    :yields: SSE formatted event strings
    :rtype: AsyncGenerator[str, None]
    """
    if not _job_worker:
        yield await format_sse_event(
            {"error": "Job worker not initialized"},
            event="error",
        )
        return

    try:
        async for event in _job_worker.get_job_events(job_id, timeout=30.0):
            yield await format_sse_event(
                {
                    "event_type": event.event_type.value,
                    "message": event.message,
                    "formatted": JobEventEmitter.format_event_as_message(event),
                    "timestamp": event.timestamp.isoformat(),
                    "step_index": event.step_index,
                    "total_steps": event.total_steps,
                    "progress_percent": event.progress_percent,
                    "details": event.details,
                },
                event=event.event_type.value,
                id=event.timestamp.isoformat(),
            )

            if event.event_type.value in ("completed", "failed", "cancelled"):
                break

    except asyncio.CancelledError:
        logger.info(f"SSE stream cancelled for job {job_id}")
        yield await format_sse_event(
            {"message": "Stream cancelled"},
            event="cancelled",
        )

    except Exception as e:
        logger.error(f"Error in SSE stream for job {job_id}: {e}")
        yield await format_sse_event(
            {"error": str(e)},
            event="error",
        )


@router.get("/jobs/{job_id}/stream")
async def stream_job_events(job_id: str, request: Request):
    """Stream job events via SSE.

    This endpoint provides real-time updates for job execution
    progress. Connect to this endpoint after submitting a job
    to receive live status updates.

    :param job_id: Job ID to stream events for
    :type job_id: str
    :param request: FastAPI request object
    :type request: Request
    :returns: SSE streaming response
    :rtype: StreamingResponse
    """

    async def event_generator():
        async for event in job_event_stream(job_id):
            if await request.is_disconnected():
                logger.info(f"Client disconnected from job {job_id} stream")
                break
            yield event

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/jobs/{job_id}/status")
async def get_job_status(job_id: str):
    """Get current job status (non-streaming).

    :param job_id: Job ID
    :type job_id: str
    :returns: Job status dict
    :rtype: dict
    """
    if not _job_worker:
        return {"error": "Job worker not initialized"}

    job = _job_worker.job_store.get_job(job_id)
    if not job:
        return {"error": "Job not found"}

    return {
        "job_id": str(job.id),
        "status": job.status.value,
        "progress_percent": job.progress_percent,
        "current_step": job.current_step,
        "summary": JobEventEmitter.format_job_summary(job),
    }


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, reason: str = "Cancelled by user"):
    """Cancel a running job.

    :param job_id: Job ID to cancel
    :type job_id: str
    :param reason: Cancellation reason
    :type reason: str
    :returns: Cancellation result
    :rtype: dict
    """
    if not _job_worker:
        return {"error": "Job worker not initialized", "cancelled": False}

    success = await _job_worker.cancel_job(job_id, reason)
    if success:
        return {"job_id": job_id, "cancelled": True, "reason": reason}
    else:
        job = _job_worker.job_store.get_job(job_id)
        if not job:
            return {"error": "Job not found", "cancelled": False}
        return {
            "error": f"Job already {job.status.value}",
            "cancelled": False,
            "status": job.status.value,
        }


class ChatStreamManager:
    """Manages streaming responses for chat with job execution.

    This class helps coordinate between the chat response and
    any background job execution, enabling real-time updates
    to be streamed back to the user.
    """

    def __init__(self, job_worker: JobWorker):
        """Initialize chat stream manager.

        :param job_worker: JobWorker for job execution
        :type job_worker: JobWorker
        """
        self.job_worker = job_worker

    async def stream_chat_with_execution(
        self,
        initial_message: str,
        job_id: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream a chat response that may include job execution.

        First yields the initial message, then if a job_id is provided,
        streams job events as they occur.

        :param initial_message: Initial assistant response
        :type initial_message: str
        :param job_id: Optional job ID for execution streaming
        :type job_id: Optional[str]
        :yields: SSE formatted messages
        :rtype: AsyncGenerator[str, None]
        """
        yield await format_sse_event(
            {
                "type": "message",
                "role": "assistant",
                "content": initial_message,
            },
            event="message",
        )

        if job_id:
            yield await format_sse_event(
                {
                    "type": "execution_started",
                    "job_id": job_id,
                },
                event="execution_started",
            )

            async for event_str in job_event_stream(job_id):
                yield event_str

        yield await format_sse_event(
            {"type": "done"},
            event="done",
        )
