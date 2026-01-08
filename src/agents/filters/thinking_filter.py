# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Function invocation filter that emits real-time thinking steps.

This filter intercepts Semantic Kernel function calls and converts them
into human-readable thinking steps, similar to ChatGPT/Claude's thinking display.
"""

from typing import Any, Callable
from semantic_kernel.filters.functions.function_invocation_context import (
    FunctionInvocationContext,
)
from semantic_kernel.filters.filter_types import FilterTypes
from semantic_kernel.functions.kernel_function_metadata import KernelFunctionMetadata

from src.agents.models.streaming import emit_thinking_step
from src.agents.observability import get_logger

logger = get_logger(__name__)


class FunctionInvocationThinkingFilter:
    """Filter that emits thinking steps when agents call functions.

    Uses function descriptions from kernel metadata (docstrings) for dynamic,
    maintainable thinking traces without hardcoded mappings.
    """

    SKIP_FUNCTIONS = {
        "should_terminate",
        "select_next_agent",
    }

    @staticmethod
    def _get_action_text(
        function_name: str, function_description: str | None, arguments: dict[str, Any]
    ) -> str:
        """Generate human-readable action text from function call and metadata.

        Uses function description from @kernel_function decorator for context.
        Enriches with argument details when helpful.
        """

        if function_description:
            desc = function_description.strip()
            if "." in desc:
                desc = desc.split(".")[0]
            if function_name == "read_workspace_file" and "filename" in arguments:
                filename = arguments["filename"]
                if filename == "sap-parameters.yaml":
                    return "Reading SAP system configuration..."
                elif filename == "hosts.yaml":
                    return "Loading host inventory..."
                return f"Reading {filename}..."

            if function_name == "resolve_user_reference" and "reference" in arguments:
                ref = arguments["reference"]
                return f"Resolving '{ref}' to workspace..."
            return f"{desc}..."

        readable = function_name.replace("_", " ").title()
        return f"{readable}..."

    async def on_function_invocation(
        self,
        context: FunctionInvocationContext,
        next: Callable[[FunctionInvocationContext], Any],
    ) -> None:
        """Called when a function is about to be invoked.

        Emits a single thinking step per function call (not duplicate in_progress/complete).
        Uses function description from kernel metadata.
        Skips internal orchestration functions.
        """

        function_name = context.function.name
        if function_name in self.SKIP_FUNCTIONS:
            await next(context)
            return

        function_description = (
            context.function.metadata.description if context.function.metadata else None
        )
        arguments = context.arguments
        action_text = self._get_action_text(
            function_name, function_description, dict(arguments) if arguments else {}
        )
        await next(context)
        try:
            await emit_thinking_step(
                agent=context.function.plugin_name or "system",
                action=action_text,
                status="complete",
            )
        except Exception as e:
            logger.warning(f"Failed to emit thinking step for {function_name}: {e}")


def register_thinking_filter(kernel) -> None:
    """Register the thinking filter with a Semantic Kernel instance."""
    filter_instance = FunctionInvocationThinkingFilter()
    kernel.add_filter(FilterTypes.FUNCTION_INVOCATION, filter_instance)
    logger.info("Registered FunctionInvocationThinkingFilter")
