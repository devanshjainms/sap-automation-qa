# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for middleware classes: Function, Chat, and Agent level."""

from __future__ import annotations
import pytest
from agent_framework import (
    AgentContext,
    AgentResponse,
    FunctionInvocationContext,
    FunctionTool,
    Message,
)
from pytest_mock import MockerFixture
from src.agents.providers.middleware import (
    AgentExceptionMiddleware,
    ErrorCategory,
    FunctionGuardMiddleware,
    _classify,
)


@pytest.fixture
def make_function_context(mocker: MockerFixture):
    """Factory fixture for ``FunctionInvocationContext``."""

    def _build(name: str = "run_evidence_collector") -> FunctionInvocationContext:
        func = mocker.MagicMock(spec=FunctionTool)
        func.name = name
        return FunctionInvocationContext(function=func, arguments={})

    return _build


@pytest.fixture
def make_agent_context(mocker: MockerFixture):
    """Factory fixture for ``AgentContext``."""

    def _build(stream: bool = False) -> AgentContext:
        agent = mocker.MagicMock()
        return AgentContext(
            agent=agent,
            messages=[Message("user", text="hello")],
            stream=stream,
        )

    return _build


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

    def test_permission_error_is_permanent(
        self, mocker: MockerFixture, make_function_context
    ) -> None:
        assert _classify(PermissionError("denied")) == ErrorCategory.PERMANENT

    def test_not_implemented_is_permanent(
        self, mocker: MockerFixture, make_function_context
    ) -> None:
        assert _classify(NotImplementedError("nope")) == ErrorCategory.PERMANENT

    def test_value_error_is_diagnostic(self, mocker: MockerFixture, make_function_context) -> None:
        assert _classify(ValueError("bad input")) == ErrorCategory.DIAGNOSTIC

    def test_runtime_error_is_diagnostic(
        self, mocker: MockerFixture, make_function_context
    ) -> None:
        assert _classify(RuntimeError("unexpected")) == ErrorCategory.DIAGNOSTIC

    def test_key_error_is_diagnostic(self, mocker: MockerFixture, make_function_context) -> None:
        assert _classify(KeyError("missing")) == ErrorCategory.DIAGNOSTIC


class TestFunctionGuardMiddleware:
    """Tests for function-level middleware."""

    @pytest.mark.asyncio
    async def test_successful_call_passes_through(
        self, mocker: MockerFixture, make_function_context
    ) -> None:
        """Happy path — result set by the tool is preserved."""
        mw = FunctionGuardMiddleware()
        ctx = make_function_context("list_workspaces")
        call_next = mocker.AsyncMock()

        async def _set_result():
            ctx.result = '{"workspaces": []}'

        call_next.side_effect = _set_result

        await mw.process(ctx, call_next)

        call_next.assert_awaited_once()
        assert ctx.result == '{"workspaces": []}'

    @pytest.mark.asyncio
    async def test_timeout_error_classified_as_transient(
        self, mocker: MockerFixture, make_function_context
    ) -> None:
        """TimeoutError → transient message with retry guidance."""
        mw = FunctionGuardMiddleware()
        ctx = make_function_context("run_evidence_collector")
        call_next = mocker.AsyncMock(side_effect=TimeoutError("timed out"))

        await mw.process(ctx, call_next)

        assert "retry" in ctx.result.lower()
        assert "run_evidence_collector" in ctx.result

    @pytest.mark.asyncio
    async def test_connection_reset_classified_as_transient(
        self, mocker: MockerFixture, make_function_context
    ) -> None:
        """ConnectionResetError → transient message."""
        mw = FunctionGuardMiddleware()
        ctx = make_function_context("query_knowledge")
        call_next = mocker.AsyncMock(side_effect=ConnectionResetError("reset"))

        await mw.process(ctx, call_next)

        assert "retry" in ctx.result.lower()
        assert "query_knowledge" in ctx.result

    @pytest.mark.asyncio
    async def test_permission_error_classified_as_permanent(
        self, mocker: MockerFixture, make_function_context
    ) -> None:
        """PermissionError → permanent message, no retry."""
        mw = FunctionGuardMiddleware()
        ctx = make_function_context("get_workspace")
        call_next = mocker.AsyncMock(side_effect=PermissionError("access denied"))

        await mw.process(ctx, call_next)

        assert "not available" in ctx.result.lower()
        assert "different approach" in ctx.result.lower()

    @pytest.mark.asyncio
    async def test_file_not_found_classified_as_permanent(
        self, mocker: MockerFixture, make_function_context
    ) -> None:
        """FileNotFoundError → permanent message."""
        mw = FunctionGuardMiddleware()
        ctx = make_function_context("missing_tool")
        call_next = mocker.AsyncMock(side_effect=FileNotFoundError("no such tool"))

        await mw.process(ctx, call_next)

        assert "not available" in ctx.result.lower()

    @pytest.mark.asyncio
    async def test_runtime_error_classified_as_diagnostic(
        self, mocker: MockerFixture, make_function_context
    ) -> None:
        """RuntimeError → diagnostic message with error text."""
        mw = FunctionGuardMiddleware()
        ctx = make_function_context("run_evidence_collector")
        call_next = mocker.AsyncMock(side_effect=RuntimeError("command returned exit code 1"))

        await mw.process(ctx, call_next)

        assert "command returned exit code 1" in ctx.result
        assert "diagnostic" in ctx.result.lower()

    @pytest.mark.asyncio
    async def test_generic_error_includes_message(
        self, mocker: MockerFixture, make_function_context
    ) -> None:
        """Non-infrastructure error includes the error text (truncated)."""
        mw = FunctionGuardMiddleware()
        ctx = make_function_context("run_evidence_collector")
        call_next = mocker.AsyncMock(side_effect=ValueError("division by zero, oops"))

        await mw.process(ctx, call_next)

        assert "division by zero" in ctx.result
        assert "different approach" in ctx.result

    @pytest.mark.asyncio
    async def test_long_error_message_truncated(
        self, mocker: MockerFixture, make_function_context, make_agent_context
    ) -> None:
        """Very long error messages are truncated to 200 chars."""
        mw = FunctionGuardMiddleware()
        ctx = make_function_context("run_evidence_collector")
        long_msg = "x" * 500
        call_next = mocker.AsyncMock(side_effect=ValueError(long_msg))

        await mw.process(ctx, call_next)
        assert "x" * 200 in ctx.result
        assert "x" * 201 not in ctx.result


class TestAgentExceptionMiddleware:
    """Tests for agent-level middleware."""

    @pytest.mark.asyncio
    async def test_successful_run_passes_through(
        self, mocker: MockerFixture, make_agent_context
    ) -> None:
        """Happy path — result set by agent is preserved."""
        mw = AgentExceptionMiddleware()
        ctx = make_agent_context()
        expected = AgentResponse(
            messages=[Message("assistant", text="All is well.")],
        )

        async def _set_result():
            ctx.result = expected

        call_next = mocker.AsyncMock(side_effect=_set_result)
        await mw.process(ctx, call_next)
        assert ctx.result is expected

    @pytest.mark.asyncio
    async def test_unhandled_exception_returns_friendly_message(
        self, mocker: MockerFixture, make_agent_context
    ) -> None:
        """Unhandled exception → friendly assistant message."""
        mw = AgentExceptionMiddleware()
        ctx = make_agent_context()
        call_next = mocker.AsyncMock(side_effect=RuntimeError("unexpected framework bug"))

        await mw.process(ctx, call_next)

        assert isinstance(ctx.result, AgentResponse)
        assert len(ctx.result.messages) == 1
        assert "unexpected problem" in ctx.result.messages[0].text

    @pytest.mark.asyncio
    async def test_keyboard_interrupt_not_caught(
        self, mocker: MockerFixture, make_agent_context
    ) -> None:
        """KeyboardInterrupt must propagate — not swallowed."""
        mw = AgentExceptionMiddleware()
        ctx = make_agent_context()
        call_next = mocker.AsyncMock(side_effect=KeyboardInterrupt)

        with pytest.raises(KeyboardInterrupt):
            await mw.process(ctx, call_next)

    @pytest.mark.asyncio
    async def test_no_stack_trace_in_response(
        self, mocker: MockerFixture, make_agent_context
    ) -> None:
        """The error response must not contain traceback details."""
        mw = AgentExceptionMiddleware()
        ctx = make_agent_context()
        call_next = mocker.AsyncMock(
            side_effect=RuntimeError("Traceback (most recent call last): File '/app/foo.py'")
        )

        await mw.process(ctx, call_next)
        response_text = ctx.result.messages[0].text
        assert "Traceback" not in response_text
        assert "/app/foo.py" not in response_text
        assert "sorry" in response_text.lower()
