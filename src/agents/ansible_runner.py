# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Ansible execution wrapper for SAP QA framework.

This module provides a safe abstraction over ansible-playbook and ansible CLI,
capturing structured output for test execution and diagnostics.
"""

import json
import tempfile
import yaml as pyyaml
import subprocess
from pathlib import Path
from typing import Any, Optional

from src.agents.observability import get_logger

logger = get_logger(__name__)


class AnsibleRunner:
    """Wrapper around Ansible CLI for controlled test execution and diagnostics."""

    def __init__(self, base_dir: Path):
        """Initialize AnsibleRunner.

        :param base_dir: Base directory for resolving relative paths (typically project root)
        :type base_dir: Path
        """
        self.base_dir = Path(base_dir)
        logger.info(f"AnsibleRunner initialized with base_dir: {self.base_dir}")

    def run_playbook(
        self,
        inventory: Path,
        playbook: Path,
        extra_vars: Optional[dict[str, Any]] = None,
        tags: Optional[list[str]] = None,
        skip_tags: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Execute ansible-playbook with given parameters.

        :param inventory: Path to Ansible inventory file (hosts.yaml)
        :type inventory: Path
        :param playbook: Path to Ansible playbook (.yml)
        :type playbook: Path
        :param extra_vars: Optional variables to pass via --extra-vars
        :type extra_vars: Optional[dict[str, Any]]
        :param tags: Optional list of tags to run
        :type tags: Optional[list[str]]
        :param skip_tags: Optional list of tags to skip
        :type skip_tags: Optional[list[str]]
        :returns: Dict containing rc (return code), stdout, stderr, command
        :rtype: dict[str, Any]
        """
        cmd = [
            "ansible-playbook",
            str(playbook),
            "-i",
            str(inventory),
        ]
        if extra_vars:
            cmd.extend(["--extra-vars", json.dumps(extra_vars)])
        if tags:
            cmd.extend(["--tags", ",".join(tags)])

        if skip_tags:
            cmd.extend(["--skip-tags", ",".join(skip_tags)])

        logger.info(f"Running ansible-playbook: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                cwd=self.base_dir,
                capture_output=True,
                text=True,
                timeout=3600,
            )

            logger.info(f"ansible-playbook completed with rc={result.returncode}")

            return {
                "rc": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "command": " ".join(cmd),
            }

        except subprocess.TimeoutExpired:
            logger.error("ansible-playbook timed out after 3600 seconds")
            return {
                "rc": -1,
                "stdout": "",
                "stderr": "Execution timed out after 3600 seconds",
                "command": " ".join(cmd),
            }
        except Exception as e:
            logger.error(f"Error running ansible-playbook: {e}")
            return {
                "rc": -1,
                "stdout": "",
                "stderr": f"Execution error: {e}",
                "command": " ".join(cmd),
            }

    def run_ad_hoc(
        self,
        inventory: Path,
        host_pattern: str,
        module: str,
        args: str,
        extra_vars: Optional[dict[str, Any]] = None,
        become: bool = False,
        loop_var: Optional[str] = None,
        loop_items: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Execute ansible ad-hoc command for diagnostics.

        :param inventory: Path to Ansible inventory file
        :type inventory: Path
        :param host_pattern: Ansible host pattern (e.g., 'db', 'all', 'scs')
        :type host_pattern: str
        :param module: Ansible module to use (e.g., 'shell', 'command', 'setup')
        :type module: str
        :param args: Module arguments (e.g., command to execute, or '{{ item }}' for loops)
        :type args: str
        :param become: Whether to use privilege escalation (sudo)
        :type become: bool
        :param loop_var: Loop variable name (e.g., 'item') for batch execution
        :type loop_var: Optional[str]
        :param loop_items: List of values to loop over (creates temp playbook)
        :type loop_items: Optional[list[str]]
        :returns: Dict containing rc, stdout, stderr, command, results, hosts
        :rtype: dict[str, Any]
        """
        if loop_items:
            logger.info(f"Running {len(loop_items)} commands sequentially via temporary playbook")
            return self._run_with_temp_playbook(
                inventory, host_pattern, module, loop_items, extra_vars, become
            )

        cmd = [
            "ansible",
            host_pattern,
            "-i",
            str(inventory),
            "-m",
            module,
            "-a",
            args,
        ]

        vars_to_pass = extra_vars.copy() if extra_vars else {}
        if loop_items:
            vars_to_pass[loop_var or "item"] = loop_items
            logger.info(f"Running {len(loop_items)} commands sequentially in single execution")

        if vars_to_pass:
            cmd.extend(["--extra-vars", json.dumps(vars_to_pass)])

        if become:
            cmd.append("--become")

        logger.info(f"Running ansible ad-hoc: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                cwd=self.base_dir,
                capture_output=True,
                text=True,
                timeout=300,
            )

            logger.info(f"ansible ad-hoc completed with rc={result.returncode}")
            ansible_results = None
            try:
                if result.stdout:
                    ansible_results = {"raw_output": result.stdout}
            except Exception:
                pass

            return {
                "rc": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "command": " ".join(cmd),
                "results": ansible_results,
                "hosts": self._parse_hosts_from_output(result.stdout),
            }

        except subprocess.TimeoutExpired:
            logger.error("ansible ad-hoc timed out after 300 seconds")
            return {
                "rc": -1,
                "stdout": "",
                "stderr": "Execution timed out after 300 seconds",
                "command": " ".join(cmd),
                "results": None,
                "hosts": [],
            }
        except Exception as e:
            logger.error(f"Error running ansible ad-hoc: {e}")
            return {
                "rc": -1,
                "stdout": "",
                "stderr": f"Execution error: {e}",
                "command": " ".join(cmd),
                "results": None,
                "hosts": [],
            }

    def _run_with_temp_playbook(
        self,
        inventory: Path,
        host_pattern: str,
        module: str,
        commands: list[str],
        extra_vars: Optional[dict[str, Any]],
        become: bool,
    ) -> dict[str, Any]:
        """Run multiple commands via temporary playbook in single execution.

        Creates temp playbook that runs all commands at once with visible output.

        :param inventory: Path to Ansible inventory
        :param host_pattern: Host pattern to target
        :param module: Ansible module (typically 'shell')
        :param commands: List of commands to execute
        :param extra_vars: Extra variables
        :param become: Use sudo
        :returns: Dict with rc, stdout, stderr, command, hosts
        """
        tasks = []
        for i, cmd in enumerate(commands):
            tasks.append(
                {
                    "name": f"Execute: {cmd}",
                    module: cmd,
                    "register": f"cmd_result_{i}",
                    "failed_when": False,
                }
            )
            tasks.append(
                {
                    "name": f"Display output for: {cmd}",
                    "ansible.builtin.debug": {
                        "msg": "{{ cmd_result_%d.stdout }}" % i,
                    },
                }
            )

        playbook_content = [
            {
                "name": "Run multiple commands in single execution",
                "hosts": host_pattern,
                "gather_facts": False,
                "become": become,
                "tasks": tasks,
            }
        ]

        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".yml", delete=False, dir=self.base_dir
            ) as f:
                pyyaml.dump(playbook_content, f, default_flow_style=False)
                temp_playbook = Path(f.name)

            logger.info(f"Created temporary playbook: {temp_playbook}")
            result = self.run_playbook(
                inventory=inventory,
                playbook=temp_playbook,
                extra_vars=extra_vars,
            )
            temp_playbook.unlink(missing_ok=True)
            hosts = self._parse_hosts_from_output(result["stdout"])

            return {
                "rc": result["rc"],
                "stdout": result["stdout"],
                "stderr": result["stderr"],
                "command": f"ansible-playbook (temp) - {len(commands)} commands",
                "results": result.get("results"),
                "hosts": hosts,
            }

        except Exception as e:
            logger.error(f"Error running temporary playbook: {e}")
            return {
                "rc": -1,
                "stdout": "",
                "stderr": f"Temp playbook error: {e}",
                "command": "ansible-playbook (temp)",
                "results": None,
                "hosts": [],
            }

    def _parse_hosts_from_output(self, output: str) -> list[str]:
        """Parse host names from Ansible output.

        :param output: Ansible command output
        :returns: List of hostnames that executed
        """
        hosts = []
        if not output:
            return hosts

        for line in output.split("\n"):
            if "|" in line and ("SUCCESS" in line or "CHANGED" in line or "FAILED" in line):
                hostname = line.split("|")[0].strip()
                if hostname and hostname not in hosts:
                    hosts.append(hostname)

        return hosts
