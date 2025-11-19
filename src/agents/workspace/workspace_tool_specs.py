# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""OpenAI tool schemas for workspace management functions.

These schemas are used with Azure OpenAI function/tool calling
to enable the LLM to interact with SAP QA workspaces.
"""


def get_workspace_tools_spec() -> list[dict]:
    """Get OpenAI tool specifications for workspace management.

    Returns:
        List of tool specification dictionaries for Azure OpenAI function calling

    Example:
        tools = get_workspace_tools_spec()
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[...],
            tools=tools,
            tool_choice="auto"
        )
    """
    return [
        {
            "type": "function",
            "function": {
                "name": "list_workspaces",
                "description": "List all existing SAP QA system workspaces. Returns workspace IDs "
                + "in format ENV-REGION-DEPLOYMENT-SID (e.g., DEV-WEEU-SAP01-X00).",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "find_workspace_by_sid_env",
                "description": "Find SAP QA workspaces matching a specific System ID (SID) and "
                + "environment. Useful when you know the SAP system but not the full workspace ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sid": {
                            "type": "string",
                            "description": "SAP System ID (3 characters, e.g., X00, P01, HDB)",
                        },
                        "env": {
                            "type": "string",
                            "description": "Environment name (e.g., DEV, QA, PROD)",
                        },
                    },
                    "required": ["sid", "env"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_workspace",
                "description": "Get full metadata for a specific SAP QA workspace by its ID. Returns"
                + " workspace details including path, environment, region, deployment code, and SID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "workspace_id": {
                            "type": "string",
                            "description": "Full workspace identifier in format ENV-REGION-"
                            + "DEPLOYMENT-SID (e.g., DEV-WEEU-SAP01-X00)",
                        },
                    },
                    "required": ["workspace_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_workspace",
                "description": "Create a new SAP QA workspace directory. The workspace ID is "
                + "automatically generated from the provided parameters in format "
                + "ENV-REGION-DEPLOYMENT-SID. If workspace already exists, returns existing metadata.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "env": {
                            "type": "string",
                            "description": "Environment name (e.g., DEV, QA, PROD)",
                        },
                        "region": {
                            "type": "string",
                            "description": "Azure region code (e.g., WEEU for West Europe, "
                            + "EAUS for East US)",
                        },
                        "deployment_code": {
                            "type": "string",
                            "description": "Deployment identifier (e.g., SAP01, SAP02)",
                        },
                        "sid": {
                            "type": "string",
                            "description": "SAP System ID (3 characters, e.g., X00, P01)",
                        },
                    },
                    "required": ["env", "region", "deployment_code", "sid"],
                },
            },
        },
    ]
