# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Generic LLM agent runner with tool calling support.

This module provides a reusable async function for running LLM agents
that can call tools/functions during conversation.
"""

import json
import logging
from typing import Callable, Any

from .llm_client import call_llm
from .logging_config import get_logger

logger = get_logger(__name__)


async def run_llm_agent(
    system_prompt: str,
    messages: list[dict],
    tools: list[dict],
    tool_handlers: dict[str, Callable[[dict], dict]],
    max_tool_rounds: int = 5,
) -> dict:
    """Run an LLM agent with tool calling capability.

    This function orchestrates a multi-turn conversation with an LLM where the model
    can call tools/functions. It handles the tool call loop, executing requested tools
    and feeding results back to the model.

    :param system_prompt: System message to prepend to the conversation
    :type system_prompt: str
    :param messages: List of message dicts with {"role": str, "content": str}
                     Roles can be: "user", "assistant", "system", "tool"
    :type messages: list[dict]
    :param tools: List of OpenAI tool specification dicts (from get_workspace_tools_spec, etc.)
    :type tools: list[dict]
    :param tool_handlers: Dict mapping tool name -> callable that takes args dict and returns result dict
    :type tool_handlers: dict[str, Callable[[dict], dict]]
    :param max_tool_rounds: Maximum number of tool call iterations to prevent infinite loops
    :type max_tool_rounds: int
    :returns: Dict with the final assistant response containing role, content, and optionally tool_calls
    :rtype: dict
    :raises RuntimeError: If tool execution fails or max_tool_rounds exceeded
    :raises ValueError: If tool arguments cannot be parsed

    Example:
        >>> from .workspace_tool_specs import get_workspace_tools_spec
        >>> from .workspace_tools import tool_list_workspaces
        >>>
        >>> result = await run_llm_agent(
        ...     system_prompt="You are a workspace manager assistant.",
        ...     messages=[{"role": "user", "content": "List all workspaces"}],
        ...     tools=get_workspace_tools_spec(),
        ...     tool_handlers={"list_workspaces": lambda args: tool_list_workspaces()},
        ... )
    """
    conversation = [{"role": "system", "content": system_prompt}] + messages.copy()

    logger.info(
        f"Starting LLM agent with {len(tools)} tools available, max {max_tool_rounds} rounds"
    )

    for round_num in range(max_tool_rounds):
        logger.info(f"Tool round {round_num + 1}/{max_tool_rounds}")
        response = await call_llm(
            messages=conversation,
            tools=tools,
            tool_choice="auto",
        )
        if not response or not response.choices:
            raise RuntimeError("Empty response from LLM")

        assistant_message = response.choices[0].message
        assistant_dict = {"role": "assistant", "content": assistant_message.content}
        if hasattr(assistant_message, "tool_calls") and assistant_message.tool_calls:
            logger.info(f"Model requested {len(assistant_message.tool_calls)} tool call(s)")
            assistant_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in assistant_message.tool_calls
            ]
            conversation.append(assistant_dict)
            for tool_call in assistant_message.tool_calls:
                tool_name = tool_call.function.name
                tool_call_id = tool_call.id

                logger.info(f"Executing tool: {tool_name} (id: {tool_call_id})")

                try:
                    try:
                        tool_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError as e:
                        error_msg = f"Failed to parse tool arguments as JSON: {e}"
                        logger.error(f"{error_msg}. Raw arguments: {tool_call.function.arguments}")
                        conversation.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call_id,
                                "name": tool_name,
                                "content": json.dumps(
                                    {
                                        "error": error_msg,
                                        "raw_arguments": tool_call.function.arguments,
                                    }
                                ),
                            }
                        )
                        continue
                    if tool_name not in tool_handlers:
                        error_msg = f"No handler found for tool '{tool_name}'"
                        logger.error(
                            f"{error_msg}. Available handlers: {list(tool_handlers.keys())}"
                        )
                        conversation.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call_id,
                                "name": tool_name,
                                "content": json.dumps(
                                    {
                                        "error": error_msg,
                                        "available_tools": list(tool_handlers.keys()),
                                    }
                                ),
                            }
                        )
                        continue
                    handler = tool_handlers[tool_name]
                    logger.debug(f"Calling handler for {tool_name} with args: {tool_args}")

                    try:
                        tool_result = handler(tool_args)
                        logger.info(f"Tool {tool_name} executed successfully")
                        logger.debug(f"Tool result: {tool_result}")
                    except Exception as e:
                        error_msg = f"Tool execution failed: {str(e)}"
                        logger.error(f"{error_msg}", exc_info=True)
                        tool_result = {"error": error_msg, "exception_type": type(e).__name__}
                    conversation.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "name": tool_name,
                            "content": json.dumps(tool_result),
                        }
                    )

                except Exception as e:
                    logger.error(
                        f"Unexpected error handling tool call {tool_name}: {e}", exc_info=True
                    )
                    conversation.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "name": tool_name,
                            "content": json.dumps(
                                {
                                    "error": f"Unexpected error: {str(e)}",
                                    "exception_type": type(e).__name__,
                                }
                            ),
                        }
                    )

            continue

        else:
            logger.info("Model provided final response without tool calls")
            conversation.append(assistant_dict)
            return assistant_dict
    logger.warning(f"Max tool rounds ({max_tool_rounds}) exceeded without final answer")
    raise RuntimeError(
        f"Agent exceeded maximum tool calling rounds ({max_tool_rounds}). "
        "The model may be stuck in a loop or unable to complete the task."
    )
