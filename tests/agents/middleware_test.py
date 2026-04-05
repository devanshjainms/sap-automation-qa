# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for middleware classes: Function, Chat, and Agent level."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from agent_framework import (
    AgentContext,
    AgentResponse,
    ChatContext,
    Content,
    FunctionInvocationContext,
    FunctionTool,
    Message,
)

from src.agents.providers.middleware import (
    AgentExceptionMiddleware,
    ErrorCategory,
    FunctionGuardMiddleware,
    _classify,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_function_context(name: str = "run_evidence_collector") -> FunctionInvocationContext:
    """Build a minimal ``FunctionInvocationContext`` with a named tool."""
    func = MagicMock(spec=FunctionTool)
    func.name = name
    return FunctionInvocationContext(function=func, arguments={})


def _make_agent_context(stream: bool = False) -> AgentContext:
    """Build a minimal ``AgentContext``."""
    agent = MagicMock()
    return AgentContext(
        agent=agent,
        messages=[Message("user", text="hello")],
        stream=stream,
    )


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------


class TestClassify:
    """Tests for type-based exception classification."""

    def test_timeout_is_transient(self) -> None:
        assert _classify(TimeoutError("timed out")) == ErrorCategory.TRANSIENT

    def test_connection_reset_is_transient(self) -> None:
        assert _classify(ConnectionResetError("reset")) == ErrorCategory.TRANSIENT

    def test_broken_pipe_is_transient(self) -> None:
        assert _classify(BrokenPipeError("pipe")) == ErrorCategory.TRANSIENT

    def test_file_not_found_is_permanent(self) -> None:
        assert _classify(FileNotFoundError("no such file")) == ErrorCategory.PERMANENT

    def test_permission_error_is_permanent(self) -> None:
        assert _classify(PermissionError("denied")) == ErrorCategory.PERMANENT

    def test_not_implemented_is_permanent(self) -> None:
        assert _classify(NotImplementedError("nope")) == ErrorCategory.PERMANENT

    def test_value_error_is_diagnostic(self) -> None:
        assert _classify(ValueError("bad input")) == ErrorCategory.DIAGNOSTIC

    def test_runtime_error_is_diagnostic(self) -> None:
        assert _classify(RuntimeError("unexpected")) == ErrorCategory.DIAGNOSTIC

    def test_key_error_is_diagnostic(self) -> None:
        assert _classify(KeyError("missing")) == ErrorCategory.DIAGNOSTIC


# ---------------------------------------------------------------------------
# FunctionGuardMiddleware
# ---------------------------------------------------------------------------


class TestFunctionGuardMiddleware:
    """Tests for function-level middleware."""

    @pytest.mark.asyncio
    async def test_successful_call_passes_through(self) -> None:
        """Happy path — result set by the tool is preserved."""
        mw = FunctionGuardMiddleware()
        ctx = _make_function_context("list_workspaces")
        call_next = AsyncMock()

        async def _set_result():
            ctx.result = '{"workspaces": []}'

        call_next.side_effect = _set_result

        await mw.process(ctx, call_next)

        call_next.assert_awaited_once()
        assert ctx.result == '{"workspaces": []}'

    @pytest.mark.asyncio
    async def test_timeout_error_classified_as_transient(self) -> None:
        """TimeoutError → transient message with retry guidance."""
        mw = FunctionGuardMiddleware()
        ctx = _make_function_context("run_evidence_collector")
        call_next = AsyncMock(side_effect=TimeoutError("timed out"))

        await mw.process(ctx, call_next)

        assert "retry" in ctx.result.lower()
        assert "run_evidence_collector" in ctx.result

    @pytest.mark.asyncio
    async def test_connection_reset_classified_as_transient(self) -> None:
        """ConnectionResetError → transient message."""
        mw = FunctionGuardMiddleware()
        ctx = _make_function_context("query_knowledge")
        call_next = AsyncMock(side_effect=ConnectionResetError("reset"))

        await mw.process(ctx, call_next)

        assert "retry" in ctx.result.lower()
        assert "query_knowledge" in ctx.result

    @pytest.mark.asyncio
    async def test_permission_error_classified_as_permanent(self) -> None:
        """PermissionError → permanent message, no retry."""
        mw = FunctionGuardMiddleware()
        ctx = _make_function_context("get_workspace")
        call_next = AsyncMock(side_effect=PermissionError("access denied"))

        await mw.process(ctx, call_next)

        assert "not available" in ctx.result.lower()
        assert "different approach" in ctx.result.lower()

    @pytest.mark.asyncio
    async def test_file_not_found_classified_as_permanent(self) -> None:
        """FileNotFoundError → permanent message."""
        mw = FunctionGuardMiddleware()
        ctx = _make_function_context("missing_tool")
        call_next = AsyncMock(side_effect=FileNotFoundError("no such tool"))

        await mw.process(ctx, call_next)

        assert "not available" in ctx.result.lower()

    @pytest.mark.asyncio
    async def test_runtime_error_classified_as_diagnostic(self) -> None:
        """RuntimeError → diagnostic message with error text."""
        mw = FunctionGuardMiddleware()
        ctx = _make_function_context("run_evidence_collector")
        call_next = AsyncMock(side_effect=RuntimeError("command returned exit code 1"))

        await mw.process(ctx, call_next)

        assert "command returned exit code 1" in ctx.result
        assert "diagnostic" in ctx.result.lower()

    @pytest.mark.asyncio
    async def test_generic_error_includes_message(self) -> None:
        """Non-infrastructure error includes the error text (truncated)."""
        mw = FunctionGuardMiddleware()
        ctx = _make_function_context("run_evidence_collector")
        call_next = AsyncMock(side_effect=ValueError("division by zero, oops"))

        await mw.process(ctx, call_next)

        assert "division by zero" in ctx.result
        assert "different approach" in ctx.result

    @pytest.mark.asyncio
    async def test_long_error_message_truncated(self) -> None:
        """Very long error messages are truncated to 200 chars."""
        mw = FunctionGuardMiddleware()
        ctx = _make_function_context("run_evidence_collector")
        long_msg = "x" * 500
        call_next = AsyncMock(side_effect=ValueError(long_msg))

        await mw.process(ctx, call_next)

        # The error portion should be at most 200 chars of the original.
        assert "x" * 200 in ctx.result
        assert "x" * 201 not in ctx.result


# ---------------------------------------------------------------------------
# AgentExceptionMiddleware
# ---------------------------------------------------------------------------


class TestAgentExceptionMiddleware:
    """Tests for agent-level middleware."""

    @pytest.mark.asyncio
    async def test_successful_run_passes_through(self) -> None:
        """Happy path — result set by agent is preserved."""
        mw = AgentExceptionMiddleware()
        ctx = _make_agent_context()
        expected = AgentResponse(
            messages=[Message("assistant", text="All is well.")],
        )

        async def _set_result():
            ctx.result = expected

        call_next = AsyncMock(side_effect=_set_result)

        await mw.process(ctx, call_next)

        assert ctx.result is expected

    @pytest.mark.asyncio
    async def test_unhandled_exception_returns_friendly_message(self) -> None:
        """Unhandled exception → friendly assistant message."""
        mw = AgentExceptionMiddleware()
        ctx = _make_agent_context()
        call_next = AsyncMock(side_effect=RuntimeError("unexpected framework bug"))

        await mw.process(ctx, call_next)

        assert isinstance(ctx.result, AgentResponse)
        assert len(ctx.result.messages) == 1
        assert "unexpected problem" in ctx.result.messages[0].text

    @pytest.mark.asyncio
    async def test_keyboard_interrupt_not_caught(self) -> None:
        """KeyboardInterrupt must propagate — not swallowed."""
        mw = AgentExceptionMiddleware()
        ctx = _make_agent_context()
        call_next = AsyncMock(side_effect=KeyboardInterrupt)

        with pytest.raises(KeyboardInterrupt):
            await mw.process(ctx, call_next)

    @pytest.mark.asyncio
    async def test_no_stack_trace_in_response(self) -> None:
        """The error response must not contain traceback details."""
        mw = AgentExceptionMiddleware()
        ctx = _make_agent_context()
        call_next = AsyncMock(
            side_effect=RuntimeError("Traceback (most recent call last): File '/app/foo.py'")
        )

        await mw.process(ctx, call_next)

        response_text = ctx.result.messages[0].text
        assert "Traceback" not in response_text
        assert "/app/foo.py" not in response_text
        assert "sorry" in response_text.lower()



