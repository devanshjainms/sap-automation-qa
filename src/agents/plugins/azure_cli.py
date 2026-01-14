# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Azure CLI plugin for querying Azure resources.

Executes Azure CLI commands from the agent container to inspect
Azure resources related to SAP deployments.
"""

import json
import subprocess
from typing import Annotated

from semantic_kernel.functions import kernel_function

from src.agents.observability import get_logger

logger = get_logger(__name__)


class AzureCLIPlugin:
    """Plugin for executing Azure CLI commands to inspect Azure resources."""

    @kernel_function(
        name="run_az_command",
        description="Execute Azure CLI command to query Azure resources. "
        "Use this to check VM details, identity assignments, RBAC roles, etc. "
        "Example: 'vm show --name myvm --resource-group myrg' or 'identity show --ids /subscriptions/.../...'",
    )
    def run_az_command(
        self,
        command: Annotated[
            str, "Azure CLI command WITHOUT 'az' prefix. E.g., 'vm list -g mygroup'"
        ],
    ) -> Annotated[str, "JSON output from Azure CLI"]:
        """Execute an Azure CLI command from the container.

        :param command: Azure CLI command without 'az' prefix
        :type command: str
        :returns: JSON string with command output
        :rtype: str
        """
        result = None
        try:
            full_command = f"az {command} --output json"

            result = subprocess.run(
                full_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
                check=True,
            )

            output_data = json.loads(result.stdout) if result.stdout.strip() else {}

            return json.dumps(
                {
                    "status": "success",
                    "output": output_data,
                },
                indent=2,
            )

        except subprocess.TimeoutExpired:
            logger.error(f"Azure CLI command timed out: {command}")
            return json.dumps(
                {
                    "status": "error",
                    "error": "Command timed out after 60 seconds",
                }
            )

        except subprocess.CalledProcessError as e:
            logger.error(f"Azure CLI command failed: {e.stderr}")
            return json.dumps(
                {
                    "status": "error",
                    "error": e.stderr.strip() if e.stderr else "Command failed",
                }
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Azure CLI output: {e}")
            return json.dumps(
                {
                    "status": "error",
                    "error": f"Invalid JSON output: {e}",
                    "raw_output": result.stdout if result else "",
                }
            )

        except Exception as e:
            logger.error(f"Azure CLI execution error: {e}")
            return json.dumps(
                {
                    "status": "error",
                    "error": str(e),
                }
            )
