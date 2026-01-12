# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Semantic Kernel plugin for SAP QA test execution.

This plugin provides safe, controlled tools for:
- Loading workspace hosts
- Running tests via Ansible playbooks
- Executing read-only diagnostic commands
- Tailing log files

All operations enforce strict safety controls and environment gating.
"""

import json
import logging
import yaml
from datetime import datetime
from pathlib import Path
from typing import Annotated, Optional, TYPE_CHECKING

from semantic_kernel.functions import kernel_function

from src.agents.constants import TEST_GROUP_PLAYBOOKS, LOG_WHITELIST
from src.agents.workspace.workspace_store import WorkspaceStore
from src.agents.ansible_runner import AnsibleRunner
from src.agents.plugins.command_validator import validate_readonly_command
from src.agents.models.execution import ExecutionResult
from src.agents.observability import get_logger

if TYPE_CHECKING:
    from src.agents.plugins.keyvault import KeyVaultPlugin
    from src.agents.plugins.workspace import WorkspacePlugin

logger = get_logger(__name__)


class ExecutionPlugin:
    """Semantic Kernel plugin for controlled SAP QA test execution."""

    def __init__(
        self,
        workspace_store: WorkspaceStore,
        ansible_runner: AnsibleRunner,
        workspace_plugin: Optional["WorkspacePlugin"] = None,
        keyvault_plugin: Optional["KeyVaultPlugin"] = None,
    ):
        """Initialize ExecutionPlugin.

        :param workspace_store: WorkspaceStore for workspace metadata access
        :type workspace_store: WorkspaceStore
        :param ansible_runner: AnsibleRunner for Ansible execution
        :type ansible_runner: AnsibleRunner
        :param workspace_plugin: WorkspacePlugin for unified context resolution
        :type workspace_plugin: Optional[WorkspacePlugin]
        :param keyvault_plugin: Optional KeyVaultPlugin for SSH key retrieval
        :type keyvault_plugin: Optional[KeyVaultPlugin]
        """
        self.workspace_store = workspace_store
        self.ansible = ansible_runner
        self.workspace_plugin = workspace_plugin
        self.keyvault_plugin = keyvault_plugin
        logger.info(
            f"ExecutionPlugin initialized "
            f"(workspace_plugin={workspace_plugin is not None}, "
            f"keyvault_enabled={keyvault_plugin is not None})"
        )

    def _get_execution_context(self, workspace_id: str) -> dict:
        """Get execution context from WorkspacePlugin - SINGLE SOURCE OF TRUTH.

        Returns dict with: inventory_path, sap_parameters, ssh_key_path, etc.
        """
        if self.workspace_plugin:
            ctx_json = self.workspace_plugin.get_execution_context(workspace_id)
            return json.loads(ctx_json)
        logger.warning("WorkspacePlugin not available")
        return {}

    @kernel_function(
        name="resolve_test_execution",
        description="Resolve which playbook and tags to use for a given test_id "
        + f"and test_group. Returns execution configuration.",
    )
    def resolve_test_execution(
        self,
        test_id: Annotated[str, "Test identifier (becomes Ansible tag)"],
        test_group: Annotated[str, "Test group (HA_DB_HANA, HA_SCS, HA_OFFLINE, CONFIG_CHECKS)"],
    ) -> Annotated[str, "JSON string with playbook, tags, and test_group"]:
        """Resolve playbook and tags for a test dynamically.

        :param test_id: Test identifier (becomes Ansible tag)
        :type test_id: str
        :param test_group: Test group (HA_DB_HANA, HA_SCS, etc.)
        :type test_group: str
        :returns: JSON string with playbook, tags, test_group
        :rtype: str
        """
        try:
            if test_group not in TEST_GROUP_PLAYBOOKS:
                return json.dumps(
                    {
                        "error": f"Unknown test_group '{test_group}'. "
                        f"Valid groups: {list(TEST_GROUP_PLAYBOOKS.keys())}"
                    }
                )

            return json.dumps(
                {
                    "playbook": TEST_GROUP_PLAYBOOKS[test_group],
                    "tags": [test_id],
                    "test_group": test_group,
                },
                indent=2,
            )

        except Exception as e:
            logger.error(f"Error resolving test execution: {e}")
            return json.dumps({"error": str(e)})

    @kernel_function(
        name="run_test_by_id",
        description="Run a specific SAP QA test by ID and test_group using Ansible playbooks. "
        + "Automatically resolves SSH key and parameters from workspace - no need to pass them.",
    )
    def run_test_by_id(
        self,
        workspace_id: Annotated[str, "Workspace ID"],
        test_id: Annotated[str, "Test ID (e.g., 'ha-config', 'azure-lb')"],
        test_group: Annotated[str, "Test group (HA_DB_HANA, HA_SCS, HA_OFFLINE, CONFIG_CHECKS)"],
    ) -> Annotated[str, "JSON string with ExecutionResult"]:
        """Run a test by ID and group via Ansible.

        :param workspace_id: Workspace identifier
        :type workspace_id: str
        :param test_id: Test ID (becomes Ansible tag)
        :type test_id: str
        :param test_group: Test group determining which playbook to use
        :type test_group: str
        :returns: JSON string with ExecutionResult
        :rtype: str
        """
        started_at = datetime.utcnow()

        try:
            ctx = self._get_execution_context(workspace_id)
            if "error" in ctx:
                return json.dumps(ctx)

            workspace = self.workspace_store.get_workspace(workspace_id)
            if not workspace:
                return json.dumps({"error": f"Workspace '{workspace_id}' not found"})
            test_config_json = self.resolve_test_execution(test_id, test_group)
            test_config = json.loads(test_config_json)
            if "error" in test_config:
                return test_config_json

            playbook_path = self.ansible.base_dir / test_config["playbook"]
            tags = test_config["tags"]
            inventory_path = Path(ctx["inventory_path"]) if ctx.get("inventory_path") else None
            if not inventory_path or not inventory_path.exists():
                return json.dumps({"error": f"Inventory not found: {ctx.get('inventory_path')}"})

            if not playbook_path.exists():
                return json.dumps({"error": f"Playbook not found at {playbook_path}"})

            extra_vars = ctx.get("sap_parameters", {}) or {}
            if ctx.get("ssh_key_path"):
                extra_vars["ansible_ssh_private_key_file"] = ctx["ssh_key_path"]
                logger.info(f"SSH key from workspace context: {ctx['ssh_key_path']}")
            else:
                logger.warning(f"No SSH key found in workspace context for {workspace_id}")

            logger.info(f"Running test {test_id} for workspace {workspace_id}")
            result = self.ansible.run_playbook(
                inventory=inventory_path,
                playbook=playbook_path,
                extra_vars=extra_vars,
                tags=tags if tags else None,
            )

            finished_at = datetime.utcnow()
            if result["rc"] == 0:
                status = "success"
                error_message = None
            elif result["rc"] == -1:
                status = "failed"
                error_message = "Execution error or timeout"
            else:
                status = "failed"
                error_message = f"Ansible playbook failed with rc={result['rc']}"
            exec_result = ExecutionResult(
                test_id=test_id,
                test_group=test_group,
                workspace_id=workspace_id,
                env=workspace.env,
                action_type="test",
                status=status,
                started_at=started_at,
                finished_at=finished_at,
                hosts=[],
                stdout=result["stdout"][:2000] if result["stdout"] else None,
                stderr=result["stderr"][:2000] if result["stderr"] else None,
                error_message=error_message,
                details={
                    "return_code": result["rc"],
                    "command": result["command"],
                    "full_stdout_length": len(result["stdout"]) if result["stdout"] else 0,
                    "full_stderr_length": len(result["stderr"]) if result["stderr"] else 0,
                },
            )

            logger.info(f"Test {test_id} completed with status: {status}")
            return json.dumps(exec_result.model_dump(), default=str, indent=2)

        except Exception as e:
            logger.error(f"Error running test {test_id}: {e}")

            exec_result = ExecutionResult(
                test_id=test_id,
                workspace_id=workspace_id,
                action_type="test",
                status="failed",
                started_at=started_at,
                finished_at=datetime.utcnow(),
                hosts=[],
                error_message=str(e),
                details={"exception": str(e)},
            )
            return json.dumps(exec_result.model_dump(), default=str, indent=2)

    def _map_role_to_inventory_group(self, role: str, sid: str) -> str:
        """Map a role name to the Ansible inventory group pattern.

        Inventory groups follow the pattern: {SID}_{ROLE}
        For example: X00_DB, X00_SCS, X00_ERS, X00_APP, X00_PAS

        :param role: Role name (db, scs, ers, app, pas, all)
        :type role: str
        :param sid: SAP System ID
        :type sid: str
        :returns: Ansible inventory group pattern
        :rtype: str
        """
        role_lower = role.lower().strip()

        if role_lower == "all":
            return "all"

        role_map = {
            "db": "DB",
            "hana": "DB",
            "database": "DB",
            "scs": "SCS",
            "ers": "ERS",
            "app": "APP",
            "pas": "PAS",
        }

        mapped_role = role_map.get(role_lower, role.upper())
        return f"{sid}_{mapped_role}"

    @kernel_function(
        name="run_readonly_command",
        description="Run a read-only diagnostic command on hosts via Ansible. "
        + "Use become=True for commands requiring sudo (pcs status, crm status, etc.). "
        + "SSH key is auto-resolved from workspace.",
    )
    def run_readonly_command(
        self,
        workspace_id: Annotated[str, "Workspace ID"],
        role: Annotated[str, "Host role (db, app, scs, ers, all)"],
        command: Annotated[str, "Read-only command to execute"],
        become: Annotated[bool, "Use sudo/become for privileged commands (default: False)"] = False,
    ) -> Annotated[str, "JSON string with ExecutionResult"]:
        """Run a validated read-only command on workspace hosts.

        SSH key is automatically resolved from workspace context.

        :param workspace_id: Workspace identifier
        :type workspace_id: str
        :param role: Host role to target
        :type role: str
        :param command: Command to execute (will be validated)
        :type command: str
        :returns: JSON string with ExecutionResult
        :rtype: str
        """
        started_at = datetime.utcnow()

        try:
            try:
                validate_readonly_command(command)
            except ValueError as e:
                logger.warning(f"Command validation failed: {e}")
                exec_result = ExecutionResult(
                    workspace_id=workspace_id,
                    action_type="command",
                    status="skipped",
                    started_at=started_at,
                    finished_at=datetime.utcnow(),
                    hosts=[],
                    error_message=f"Command rejected by safety validation: {e}",
                    details={"validation_error": str(e), "command": command},
                )
                return json.dumps(exec_result.model_dump(), default=str, indent=2)
            ctx = self._get_execution_context(workspace_id)
            if "error" in ctx:
                return json.dumps(ctx)

            workspace = self.workspace_store.get_workspace(workspace_id)
            if not workspace:
                return json.dumps({"error": f"Workspace '{workspace_id}' not found"})
            inventory_path = Path(ctx["inventory_path"]) if ctx.get("inventory_path") else None
            if not inventory_path or not inventory_path.exists():
                return json.dumps({"error": f"Inventory not found: {ctx.get('inventory_path')}"})

            host_pattern = self._map_role_to_inventory_group(role, workspace.sid)
            logger.info(
                f"Running validated read-only command on {role} hosts "
                f"(pattern: {host_pattern}): {command}"
            )
            extra_vars: dict[str, str] = {}
            if ctx.get("ssh_key_path"):
                extra_vars["ansible_ssh_private_key_file"] = ctx["ssh_key_path"]
                logger.info(f"SSH key from workspace context: {ctx['ssh_key_path']}")
            else:
                logger.warning(
                    f"No SSH key found in workspace context for {workspace_id}, "
                    "using Ansible defaults"
                )

            result = self.ansible.run_ad_hoc(
                inventory=inventory_path,
                host_pattern=host_pattern,
                module="shell",
                args=command,
                extra_vars=extra_vars if extra_vars else None,
                become=become,
            )

            finished_at = datetime.utcnow()
            if result["rc"] == 0:
                status = "success"
                error_message = None
            elif result["rc"] == -1:
                status = "failed"
                error_message = "Execution error or timeout"
            else:
                status = "partial"
                error_message = f"Command completed with rc={result['rc']}"

            exec_result = ExecutionResult(
                workspace_id=workspace_id,
                env=workspace.env,
                action_type="command",
                status=status,
                started_at=started_at,
                finished_at=finished_at,
                hosts=[role],
                stdout=result["stdout"][:2000] if result["stdout"] else None,
                stderr=result["stderr"][:2000] if result["stderr"] else None,
                error_message=error_message,
                details={
                    "return_code": result["rc"],
                    "command": command,
                    "role": role,
                    "full_stdout_length": len(result["stdout"]) if result["stdout"] else 0,
                },
            )

            logger.info(f"Read-only command completed with status: {status}")

            return json.dumps(exec_result.model_dump(), default=str, indent=2)

        except Exception as e:
            logger.error(f"Error running command: {e}")

            exec_result = ExecutionResult(
                workspace_id=workspace_id,
                action_type="command",
                status="failed",
                started_at=started_at,
                finished_at=datetime.utcnow(),
                hosts=[],
                error_message=str(e),
                details={"exception": str(e), "command": command},
            )

            return json.dumps(exec_result.model_dump(), default=str, indent=2)

    @kernel_function(
        name="tail_log", description="Tail a whitelisted log file for a given role in the workspace"
    )
    def tail_log(
        self,
        workspace_id: Annotated[str, "Workspace ID"],
        role: Annotated[str, "Host role (db, scs, app, system)"],
        log_type: Annotated[str, "Log type (hana_trace, hana_alert, sap_log, messages, syslog)"],
        lines: Annotated[int, "Number of lines to tail"] = 200,
    ) -> Annotated[str, "JSON string with ExecutionResult containing log tail"]:
        """Tail a whitelisted log file.

        :param workspace_id: Workspace identifier
        :type workspace_id: str
        :param role: Host role
        :type role: str
        :param log_type: Type of log from whitelist
        :type log_type: str
        :param lines: Number of lines to tail
        :type lines: int
        :returns: JSON string with ExecutionResult
        :rtype: str
        """
        started_at = datetime.utcnow()

        try:
            log_key = (role, log_type)
            if log_key not in LOG_WHITELIST:
                available = [f"{r}/{lt}" for r, lt in LOG_WHITELIST.keys()]
                return json.dumps(
                    {
                        "error": f"Log type '{role}/{log_type}' not in whitelist. Available: {available}"
                    }
                )

            log_pattern = LOG_WHITELIST[log_key]
            command = f"tail -n {lines} {log_pattern}"
            validate_readonly_command(command)
            return self.run_readonly_command(workspace_id, role, command)

        except Exception as e:
            logger.error(f"Error tailing log: {e}")

            exec_result = ExecutionResult(
                workspace_id=workspace_id,
                action_type="log",
                status="failed",
                started_at=started_at,
                finished_at=datetime.utcnow(),
                hosts=[],
                error_message=str(e),
                details={"exception": str(e)},
            )

            return json.dumps(exec_result.model_dump(), default=str, indent=2)
