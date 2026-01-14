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
import re
import yaml
from datetime import datetime
from pathlib import Path
from typing import Annotated, Optional, TYPE_CHECKING, Union, Any
from uuid import UUID
from semantic_kernel.functions import kernel_function

from src.agents.constants import TEST_GROUP_PLAYBOOKS, LOG_WHITELIST
from src.agents.workspace.workspace_store import WorkspaceStore
from src.agents.ansible_runner import AnsibleRunner
from src.agents.plugins.command_validator import validate_readonly_command
from src.agents.request_context import RequestContext
from src.agents.models.execution import ExecutionResult
from src.agents.execution.store import JobStore
from src.agents.observability import get_logger
from src.agents.models.job import JobStatus

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
        job_store: Optional[JobStore] = None,
        workspace_plugin: Optional["WorkspacePlugin"] = None,
        keyvault_plugin: Optional["KeyVaultPlugin"] = None,
    ):
        """Initialize ExecutionPlugin.

        :param workspace_store: WorkspaceStore for workspace metadata access
        :type workspace_store: WorkspaceStore
        :param ansible_runner: AnsibleRunner for Ansible execution
        :type ansible_runner: AnsibleRunner
        :param job_store: JobStore for persisting execution history (optional)
        :type job_store: Optional[JobStore]
        :param workspace_plugin: WorkspacePlugin for unified context resolution
        :type workspace_plugin: Optional[WorkspacePlugin]
        :param keyvault_plugin: Optional KeyVaultPlugin for SSH key retrieval
        :type keyvault_plugin: Optional[KeyVaultPlugin]
        """
        self.workspace_store = workspace_store
        self.ansible = ansible_runner
        self.job_store = job_store or JobStore()
        self.workspace_plugin = workspace_plugin
        self.keyvault_plugin = keyvault_plugin
        logger.info(
            f"ExecutionPlugin initialized "
            f"(workspace_plugin={workspace_plugin is not None}, "
            f"keyvault_enabled={keyvault_plugin is not None}, "
            f"job_store={job_store is not None})"
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

    def _get_conversation_id(self, provided_id: str = "") -> Optional[str]:
        """Get conversation ID from provided parameter or RequestContext.

        :param provided_id: Explicitly provided conversation ID
        :type provided_id: str
        :returns: Conversation ID or None
        :rtype: Optional[str]
        """
        if provided_id:
            return provided_id
        return RequestContext.get_conversation_id()

    def _store_command_execution(
        self,
        workspace_id: str,
        role: str,
        command: str,
        conversation_id: str = "",
        result: Optional[ExecutionResult] = None,
        job_id: str = "",
        target_node: str = "",
        target_nodes: Optional[list[str]] = None,
        raw_stdout: Optional[str] = None,
        raw_stderr: Optional[str] = None,
    ) -> None:
        """Store command execution to database for query history.

        :param workspace_id: Workspace ID
        :type workspace_id: str
        :param role: Host role targeted
        :type role: str
        :param command: Command executed
        :type command: str
        :param conversation_id: Conversation ID (falls back to RequestContext)
        :type conversation_id: str
        :param result: Execution result
        :type result: Optional[ExecutionResult]
        :param job_id: Existing job ID to update (optional)
        :type job_id: str
        :param target_node: Primary target node/host name
        :type target_node: str
        :param target_nodes: List of target nodes/hosts
        :type target_nodes: Optional[list[str]]
        :param raw_stdout: Full raw stdout (not truncated)
        :type raw_stdout: Optional[str]
        :param raw_stderr: Full raw stderr (not truncated)
        :type raw_stderr: Optional[str]
        """
        resolved_conversation_id = self._get_conversation_id(conversation_id)

        logger.info(
            f"_store_command_execution called: job_id={job_id or 'NONE'}, "
            f"conversation_id={resolved_conversation_id or 'NONE'}, workspace_id={workspace_id}, "
            f"command={command}, target_node={target_node or 'NONE'}"
        )

        try:
            if job_id:
                logger.info(f"Attempting to update existing job: {job_id}")
                try:
                    job = self.job_store.get_job(UUID(job_id))
                    if job:
                        final_status = (
                            JobStatus.COMPLETED
                            if result and result.status == "success"
                            else JobStatus.FAILED
                        )
                        job.status = final_status
                        job.started_at = job.started_at or datetime.utcnow()
                        job.completed_at = datetime.utcnow()
                        job.target_node = target_node or job.target_node
                        job.target_nodes = target_nodes or job.target_nodes
                        job.raw_stdout = raw_stdout
                        job.raw_stderr = raw_stderr
                        if result:
                            job.result = result.model_dump(mode="json")

                        self.job_store.update_job(job)
                        logger.info(f"Updated job {job_id} with execution result")
                        return
                except (ValueError, AttributeError) as e:
                    logger.warning(f"Invalid job_id {job_id}: {e}, creating new job")

            logger.info(
                f"Creating new ad-hoc job: conversation_id={resolved_conversation_id or 'NONE'}"
            )
            job = self.job_store.create_job(
                workspace_id=workspace_id,
                test_id=f"command:{command.split()[0]}",
                test_group="adhoc_command",
                test_ids=[],
                conversation_id=resolved_conversation_id,
                user_id=RequestContext.get_user_id(),
                target_node=target_node or None,
                target_nodes=target_nodes,
                metadata={
                    "command": command,
                    "role": role,
                    "type": "readonly_command",
                },
            )
            job.status = (
                JobStatus.COMPLETED if result and result.status == "success" else JobStatus.FAILED
            )
            job.started_at = datetime.utcnow()
            job.completed_at = datetime.utcnow()
            job.raw_stdout = raw_stdout
            job.raw_stderr = raw_stderr
            if result:
                job.result = result.model_dump(mode="json")
            self.job_store.update_job(job)

            logger.info(
                f"Stored command execution: {job.id}, status={job.status.value}, "
                f"workspace={workspace_id}, role={role}, command={command.split()[0]}"
            )

        except Exception as e:
            logger.error(
                f"Failed to store command execution: {e}",
                extra={"error": str(e), "traceback": True},
            )

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
        job_id: Annotated[str, "Optional job ID to update (for tracking)"] = "",
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
                stdout=result["stdout"][:8000] if result["stdout"] else None,
                stderr=result["stderr"][:8000] if result["stderr"] else None,
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
        description="Run read-only diagnostic command(s) on hosts via Ansible. "
        + "Accepts single command (str) or multiple commands (list[str]). Multiple commands "
        + "run sequentially in a single Ansible execution to reduce connection overhead. "
        + "Use become=True for commands requiring sudo (pcs status, crm status, etc.). "
        + "SSH key is auto-resolved from workspace.",
    )
    def run_readonly_command(
        self,
        workspace_id: Annotated[str, "Workspace ID"],
        role: Annotated[str, "Host role (db, app, scs, ers, all)"],
        command: Annotated[
            Union[str, list[str]], "Command or list of commands to execute sequentially"
        ],
        become: Annotated[bool, "Use sudo/become for privileged commands (default: False)"] = False,
        job_id: Annotated[str, "Optional job ID to update (for tracking)"] = "",
    ) -> Annotated[str, "JSON string with ExecutionResult"]:
        """Run validated read-only command(s) on workspace hosts.

        SSH key is automatically resolved from workspace context.
        Conversation ID is obtained from RequestContext (set by orchestrator).

        :param workspace_id: Workspace identifier
        :type workspace_id: str
        :param role: Host role to target
        :type role: str
        :param command: Command or list of commands to execute (will be validated)
        :type command: Union[str, list[str]]
        :param become: Use sudo for privileged commands
        :type become: bool
        :param job_id: Optional job ID for tracking
        :type job_id: str
        :returns: JSON string with ExecutionResult
        :rtype: str
        """
        started_at = datetime.utcnow()
        commands = command if isinstance(command, list) else [command]
        is_multiple = isinstance(command, list)

        try:
            for cmd in commands:
                try:
                    validate_readonly_command(cmd)
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
                        details={"validation_error": str(e), "command": cmd},
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
                f"Running {len(commands)} command(s) on {role} hosts (pattern: {host_pattern})"
            )
            extra_vars: dict[str, Any] = {}
            if ctx.get("ssh_key_path"):
                extra_vars["ansible_ssh_private_key_file"] = ctx["ssh_key_path"]
                logger.info(f"SSH key from workspace context: {ctx['ssh_key_path']}")
            else:
                logger.warning(
                    f"No SSH key found in workspace context for {workspace_id}, "
                    "using Ansible defaults"
                )
            if is_multiple:
                result = self.ansible.run_ad_hoc(
                    inventory=inventory_path,
                    host_pattern=host_pattern,
                    module="shell",
                    args="{{ item }}",
                    extra_vars=extra_vars,
                    become=become,
                    loop_var="item",
                    loop_items=commands,
                )
            else:
                result = self.ansible.run_ad_hoc(
                    inventory=inventory_path,
                    host_pattern=host_pattern,
                    module="shell",
                    args=commands[0],
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

            target_nodes_list = result.get("hosts", []) or []
            primary_target = target_nodes_list[0] if target_nodes_list else host_pattern

            exec_result = ExecutionResult(
                workspace_id=workspace_id,
                env=workspace.env,
                action_type="command",
                status=status,
                started_at=started_at,
                finished_at=finished_at,
                hosts=target_nodes_list or [role],
                stdout=result["stdout"][:8000] if result["stdout"] else None,
                stderr=result["stderr"][:8000] if result["stderr"] else None,
                error_message=error_message,
                details={
                    "return_code": result["rc"],
                    "command": commands[0] if len(commands) == 1 else f"{len(commands)} commands",
                    "commands": commands if len(commands) > 1 else None,
                    "role": role,
                    "host_pattern": host_pattern,
                    "full_stdout_length": len(result["stdout"]) if result["stdout"] else 0,
                },
            )

            logger.info(f"Command execution completed with status: {status}")
            command_str = json.dumps(commands) if is_multiple else commands[0]
            self._store_command_execution(
                workspace_id=workspace_id,
                role=role,
                command=command_str,
                result=exec_result,
                job_id=job_id,
                target_node=primary_target,
                target_nodes=target_nodes_list,
                raw_stdout=result.get("stdout"),
                raw_stderr=result.get("stderr"),
            )

            return json.dumps(exec_result.model_dump(), default=str, indent=2)

        except Exception as e:
            logger.error(f"Error running command: {e}")

            command_str = json.dumps(commands) if is_multiple else commands[0]
            exec_result = ExecutionResult(
                workspace_id=workspace_id,
                action_type="command",
                status="failed",
                started_at=started_at,
                finished_at=datetime.utcnow(),
                hosts=[],
                error_message=str(e),
                details={
                    "exception": str(e),
                    "command": command_str,
                    "commands": commands if len(commands) > 1 else None,
                },
            )
            self._store_command_execution(
                workspace_id=workspace_id,
                role=role,
                command=command_str,
                result=exec_result,
                job_id=job_id,
                target_node=role,
                raw_stderr=str(e),
            )

            return json.dumps(exec_result.model_dump(), default=str, indent=2)

    @kernel_function(
        name="tail_log",
        description="Tail a whitelisted log file for investigation or general viewing",
    )
    def tail_log(
        self,
        workspace_id: Annotated[str, "Workspace ID"],
        role: Annotated[str, "Host role (db, scs, app, system)"],
        log_type: Annotated[str, "Log type (hana_trace, hana_alert, sap_log, messages, syslog)"],
        lines: Annotated[int, "Number of lines to tail"] = 200,
        pattern: Annotated[
            str,
            "Optional grep pattern to filter log content. Leave empty for no filtering. Example: 'error|fail|critical'",
        ] = "",
        investigation: Annotated[
            bool,
            "Investigation mode: adds context lines, timestamps, and deduplication for "
            + "root cause analysis",
        ] = False,
        context_lines: Annotated[
            int,
            "Number of context lines before/after pattern match (investigation mode only)",
        ] = 5,
    ) -> Annotated[str, "JSON string with ExecutionResult containing log tail"]:
        """Tail a whitelisted log file with optional investigation mode.

        Investigation mode extracts focused excerpts with context for troubleshooting.
        Regular mode shows raw tail output.

        :param workspace_id: Workspace identifier
        :type workspace_id: str
        :param role: Host role
        :type role: str
        :param log_type: Type of log from whitelist
        :type log_type: str
        :param lines: Number of lines to tail
        :type lines: int
        :param pattern: Grep pattern for filtering (empty string means no filter)
        :type pattern: str
        :param investigation: Enable investigation mode (context + dedup)
        :type investigation: bool
        :param context_lines: Context lines around matches (investigation mode)
        :type context_lines: int
        :returns: JSON string with ExecutionResult
        :rtype: str
        """
        started_at = datetime.utcnow()
        pattern_to_use = pattern if pattern and pattern.strip() else None

        try:
            log_key = (role, log_type)
            if log_key not in LOG_WHITELIST:
                available = [f"{r}/{lt}" for r, lt in LOG_WHITELIST.keys()]
                return json.dumps(
                    {
                        "error": f"Log type '{role}/{log_type}' not in whitelist. "
                        + f"Available: {available}"
                    }
                )

            log_pattern = LOG_WHITELIST[log_key]
            if investigation and pattern_to_use:
                if any(char in pattern_to_use for char in [";", "&", "$", "`", "\n", "\r"]):
                    return json.dumps(
                        {
                            "error": "Invalid characters in grep pattern. "
                            + "Use only regex metacharacters."
                        }
                    )
                ctx = max(1, min(context_lines, 10))
                command = (
                    f"grep -iEnC{ctx} --group-separator=--- "
                    + f"'{pattern_to_use}' {log_pattern} 2>/dev/null | "
                    f"tail -n {lines}"
                )

            elif pattern_to_use:
                if any(char in pattern_to_use for char in [";", "&", "$", "`", "\n", "\r"]):
                    return json.dumps({"error": "Invalid characters in grep pattern."})
                command = f"grep -iE '{pattern_to_use}' {log_pattern} 2>/dev/null | tail -n {lines}"

            elif investigation:
                if "messages" in log_type or "syslog" in log_type:
                    command = (
                        f"tail -n {lines} {log_pattern} 2>/dev/null "
                        + "|| echo 'Log file not accessible'"
                    )
                else:
                    command = (
                        f"tail -n {lines} {log_pattern} 2>/dev/null "
                        + "|| echo 'Log file not accessible'"
                    )

            else:
                command = (
                    f"tail -n {lines} {log_pattern} 2>/dev/null || echo 'Log file not accessible'"
                )

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

    @kernel_function(
        name="get_recent_executions",
        description="Get recent command executions and test runs for a conversation or workspace. "
        "Use this to answer 'which node?', 'what did you just run?', or 'show execution history'.",
    )
    def get_recent_executions(
        self,
        workspace_id: Annotated[str, "Optional: Filter by workspace"] = "",
        limit: Annotated[int, "Max results to return"] = 10,
    ) -> Annotated[str, "JSON list of recent executions"]:
        """Query recent executions from database.

        Uses RequestContext to get conversation_id automatically - no parameter injection needed.

        :param workspace_id: Optional workspace filter
        :type workspace_id: str
        :param limit: Max results
        :type limit: int
        :returns: JSON with execution history
        :rtype: str
        """
        try:
            conversation_id = RequestContext.get_conversation_id()
            logger.info(
                f"get_recent_executions called: conversation_id={conversation_id or 'NONE'}, "
                f"workspace_id={workspace_id or 'NONE'}, limit={limit}"
            )

            if conversation_id:
                jobs = self.job_store.get_jobs_for_conversation(conversation_id, limit=limit)
                logger.info(f"Found {len(jobs)} jobs for conversation {conversation_id}")
                if workspace_id:
                    jobs = [j for j in jobs if j.workspace_id == workspace_id]
                    logger.info(f"After workspace filter: {len(jobs)} jobs")
            else:
                jobs = self.job_store.get_job_history(
                    user_id=None, workspace_id=workspace_id or None, limit=limit
                )
                logger.info(f"Found {len(jobs)} jobs from history (no conversation_id)")

            results = []
            for job in jobs:
                command = ""
                if job.test_id:
                    command = job.test_id.split(":", 1)[1] if ":" in job.test_id else job.test_id

                result_summary = None
                if job.result and isinstance(job.result, dict):
                    result_summary = {
                        "status": job.result.get("status"),
                        "stdout_length": (
                            len(job.result.get("stdout", "")) if job.result.get("stdout") else 0
                        ),
                        "stderr_length": (
                            len(job.result.get("stderr", "")) if job.result.get("stderr") else 0
                        ),
                    }

                results.append(
                    {
                        "job_id": str(job.id),
                        "workspace_id": job.workspace_id,
                        "test_id": job.test_id,
                        "command": command,
                        "test_group": job.test_group,
                        "status": job.status.value,
                        "target_node": job.target_node,
                        "target_nodes": job.target_nodes,
                        "created_at": job.created_at.isoformat(),
                        "started_at": job.started_at.isoformat() if job.started_at else None,
                        "result_summary": result_summary,
                        "metadata": job.metadata,
                    }
                )

            return json.dumps({"executions": results, "count": len(results)}, indent=2)

        except Exception as e:
            logger.error(f"Error querying executions: {e}")
            return json.dumps({"error": str(e)})

    @kernel_function(
        name="get_job_output",
        description=(
            "Get the full output/result of a specific job by its ID. "
            "Use this when the user asks 'show me the output' or 'what was the result' "
            "of a command that was already executed. Requires the job_id from get_recent_executions."
        ),
    )
    def get_job_output(
        self,
        job_id: Annotated[str, "The job ID to retrieve output for"],
    ) -> Annotated[str, "JSON with job details and output"]:
        """Get full output for a specific job.

        :param job_id: Job ID to retrieve
        :type job_id: str
        :returns: JSON with job details including stdout/result
        :rtype: str
        """
        try:
            job = self.job_store.get_job(UUID(job_id))
            if not job:
                return json.dumps({"error": f"Job {job_id} not found"})

            result = {
                "job_id": str(job.id),
                "workspace_id": job.workspace_id,
                "test_id": job.test_id,
                "status": job.status.value,
                "created_at": job.created_at.isoformat(),
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                "metadata": job.metadata,
            }
            if job.result:
                result["output"] = job.result

            if job.error_message:
                result["error_message"] = job.error_message

            logger.info(f"Retrieved job output for {job_id}")
            return json.dumps(result, indent=2, default=str)

        except Exception as e:
            logger.error(f"Error getting job output: {e}")
            return json.dumps({"error": str(e)})
