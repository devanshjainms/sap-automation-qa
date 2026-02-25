# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Test orchestrator for E2E release validation.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from e2e.src.azure_deployer import DeployedVM
from e2e.src.config import (
    E2EConfig,
    ExecutionMode,
    TestGroup,
)
from e2e.src.models import (
    DeployerResult,
    Outcome,
    TestResult,
)
from e2e.src.remote_executor import RemoteExecutor

from e2e.src.workspace_discovery import (
    WorkspaceCapability,
    discover_workspaces,
)

logger = logging.getLogger(__name__)

_REPO_DIR = "/root/sap-automation-qa"


class TestOrchestrator:
    """Drives the full E2E flow on one deployer VM.

    :param vm: Deployed VM to orchestrate.
    :param config: E2E configuration.
    """

    def __init__(self, vm: DeployedVM, config: E2EConfig) -> None:
        self._vm = vm
        self._cfg = config
        self._executor = RemoteExecutor(vm)
        self._repo_dir = _REPO_DIR
        self._prepared = False

    def prepare(self) -> tuple[Outcome, str]:
        """One-time VM preparation: SSH, git, clone.

        Idempotent — subsequent calls return immediately.

        :returns: (outcome, error_message) tuple.
        :rtype: tuple[Outcome, str]
        """
        if self._prepared:
            return Outcome.PASSED, ""

        if not self._executor.wait_for_ssh(retries=30, delay=10):
            return Outcome.ERROR, "SSH never reachable"

        if self._install_git() != 0:
            return Outcome.ERROR, "Failed to install git"

        if self._clone_repo() != 0:
            return (
                Outcome.ERROR,
                "Failed to clone repository",
            )

        self._prepared = True
        return Outcome.PASSED, ""

    def run(self, mode: ExecutionMode) -> DeployerResult:
        """Execute the full user workflow for a given mode.

        :param mode: LOCAL or CONTAINER execution mode.
        :returns: Aggregated results for this deployer + mode.
        :rtype: DeployerResult
        """
        result = DeployerResult(
            distro=self._vm.distro.value,
            execution_mode=mode.value,
            vm_name=self._vm.vm_name,
            private_ip=self._vm.private_ip,
            started_at=datetime.now(timezone.utc),
        )

        prep_outcome, prep_err = self.prepare()
        if prep_outcome != Outcome.PASSED:
            result.setup_outcome = prep_outcome
            result.setup_stderr = prep_err
            result.finished_at = datetime.now(timezone.utc)
            return result

        setup = self._run_setup(mode)
        result.setup_duration_seconds = setup.duration_seconds
        result.setup_stdout = setup.stdout
        result.setup_stderr = setup.stderr

        if setup.return_code != 0:
            result.setup_outcome = Outcome.FAILED
            result.finished_at = datetime.now(timezone.utc)
            return result

        result.setup_outcome = Outcome.PASSED
        if mode == ExecutionMode.CONTAINER:
            if not self._wait_for_api():
                result.setup_outcome = Outcome.FAILED
                result.setup_stderr = "Container API never became healthy"
                result.finished_at = datetime.now(timezone.utc)
                return result
        workspaces = discover_workspaces(self._executor, self._cfg, self._repo_dir)
        result.workspaces_discovered = [w.workspace_id for w in workspaces]

        if not workspaces:
            logger.warning(
                "No testable workspaces on %s (%s)",
                self._vm.vm_name,
                self._vm.distro.value,
            )
            result.finished_at = datetime.now(timezone.utc)
            return result

        if self._cfg.dry_run:
            logger.info(
                "Dry run — skipping test execution on %s",
                self._vm.vm_name,
            )
            result.finished_at = datetime.now(timezone.utc)
            return result
        enabled_groups = self._cfg.enabled_test_groups()

        if TestGroup.CONFIGURATION_CHECKS in enabled_groups:
            for ws in workspaces:
                if TestGroup.CONFIGURATION_CHECKS.value not in ws.applicable_groups:
                    result.test_results.append(
                        TestResult(
                            workspace_id=ws.workspace_id,
                            test_group=(TestGroup.CONFIGURATION_CHECKS.value),
                            outcome=Outcome.SKIPPED,
                        )
                    )
                    continue

                test_result = self._run_test_group(
                    ws,
                    TestGroup.CONFIGURATION_CHECKS,
                    mode,
                )
                result.test_results.append(test_result)
        functional_groups = [
            g
            for g in (
                TestGroup.CENTRAL_SERVICES_HA,
                TestGroup.DATABASE_HA,
            )
            if g in enabled_groups
        ]

        for ws in workspaces:
            for group in functional_groups:
                if group.value not in ws.applicable_groups:
                    result.test_results.append(
                        TestResult(
                            workspace_id=ws.workspace_id,
                            test_group=group.value,
                            outcome=Outcome.SKIPPED,
                        )
                    )
                    continue

                test_result = self._run_test_group(ws, group, mode)
                result.test_results.append(test_result)

        result.finished_at = datetime.now(timezone.utc)
        return result

    def _install_git(self) -> int:
        """Install git on the VM (step 1.2 from SETUP.MD).

        :returns: Exit code.
        :rtype: int
        """
        install_cmd = (
            "if command -v git &>/dev/null; then "
            "echo 'git already installed'; exit 0; "
            "fi; "
            "if command -v apt-get &>/dev/null; then "
            "sudo apt-get update -y && "
            "sudo apt-get install -y git; "
            "elif command -v yum &>/dev/null; then "
            "sudo yum install -y git; "
            "elif command -v zypper &>/dev/null; then "
            "sudo zypper install -y git; "
            "else "
            "echo 'No package manager found'; exit 1; "
            "fi"
        )
        r = self._executor.run(install_cmd, timeout=300)
        if r.return_code != 0:
            logger.error(
                "git install failed on %s: %s",
                self._vm.vm_name,
                r.stderr,
            )
        return r.return_code

    def _clone_repo(self) -> int:
        """Clone the repo and checkout the target ref (step 1.3).

        :returns: Exit code.
        :rtype: int
        """
        clone_cmd = (
            f"sudo rm -rf {self._repo_dir} && "
            f"sudo git clone {self._cfg.github_repo} "
            f"{self._repo_dir} && "
            f"cd {self._repo_dir} && "
            f"sudo git checkout {self._cfg.github_ref}"
        )
        r = self._executor.run(clone_cmd, timeout=300)
        if r.return_code != 0:
            logger.error(
                "Clone failed on %s: %s",
                self._vm.vm_name,
                r.stderr,
            )
        return r.return_code

    def _run_setup(self, mode: ExecutionMode):
        """Run ``./scripts/setup.sh`` for the given mode.

        :param mode: Execution mode.
        :returns: Remote execution result.
        :rtype: RemoteResult
        """
        if mode == ExecutionMode.CONTAINER:
            cmd = f"cd {self._repo_dir} && " "sudo ./scripts/setup.sh container start"
        else:
            cmd = f"cd {self._repo_dir} && " "sudo ./scripts/setup.sh"

        logger.info(
            "Running setup.sh on %s (%s)...",
            self._vm.vm_name,
            self._vm.distro.value,
        )
        return self._executor.run(cmd, timeout=900)

    def _wait_for_api(self) -> bool:
        """Wait for the container API health endpoint.

        :returns: True if API became healthy.
        :rtype: bool
        """
        for attempt in range(1, self._cfg.health_retries + 1):
            r = self._executor.run(
                "curl -sf http://localhost:8000/healthz",
                timeout=15,
            )
            if r.return_code == 0:
                logger.info(
                    "Container API healthy on %s " "(attempt %d)",
                    self._vm.vm_name,
                    attempt,
                )
                return True
            time.sleep(self._cfg.health_retry_delay)

        logger.error(
            "Container API never healthy on %s",
            self._vm.vm_name,
        )
        return False

    def _configure_vars_yaml(
        self,
        ws: WorkspaceCapability,
        test_group: TestGroup,
    ) -> int:
        """Update vars.yaml for the given workspace+test (step 2.1.2).

        Writes vars.yaml just like a user would: set TEST_TYPE,
        SAP_FUNCTIONAL_TEST_TYPE, SYSTEM_CONFIG_NAME, etc.

        :param ws: Target workspace.
        :param test_group: Test group to configure.
        :returns: Exit code.
        :rtype: int
        """
        _GROUP_VARS: dict[TestGroup, tuple[str, str]] = {
            TestGroup.CONFIGURATION_CHECKS: (
                "ConfigurationChecks",
                "",
            ),
            TestGroup.DATABASE_HA: (
                "SAPFunctionalTests",
                "DatabaseHighAvailability",
            ),
            TestGroup.CENTRAL_SERVICES_HA: (
                "SAPFunctionalTests",
                "CentralServicesHighAvailability",
            ),
        }
        test_type, func_type = _GROUP_VARS[test_group]
        auth_type = self._cfg.authentication_type

        vars_content = f"""TEST_TYPE: "{test_type}"
SAP_FUNCTIONAL_TEST_TYPE: "{func_type}"
SYSTEM_CONFIG_NAME: "{ws.workspace_id}"
WORKSPACES_DIR: "WORKSPACES"
AUTHENTICATION_TYPE: "{auth_type}"
"""
        cmd = f"cat > {self._repo_dir}/vars.yaml << 'VARSEOF'\n" f"{vars_content}" "VARSEOF"
        r = self._executor.run(cmd, timeout=30)
        return r.return_code

    def _run_test_group(
        self,
        ws: WorkspaceCapability,
        test_group: TestGroup,
        mode: ExecutionMode,
    ) -> TestResult:
        """Execute one test group on one workspace.

        Replicates the user running:
        ``./scripts/sap_automation_qa.sh``
        after configuring vars.yaml.

        :param ws: Target workspace.
        :param test_group: Test group to run.
        :param mode: Execution mode (LOCAL or CONTAINER).
        :returns: Test execution result.
        :rtype: TestResult
        """
        logger.info(
            "Running %s on workspace %s (%s / %s)",
            test_group.value,
            ws.workspace_id,
            self._vm.distro.value,
            self._vm.vm_name,
        )

        cfg_rc = self._configure_vars_yaml(ws, test_group)
        if cfg_rc != 0:
            return TestResult(
                workspace_id=ws.workspace_id,
                test_group=test_group.value,
                outcome=Outcome.ERROR,
                error_message="Failed to configure vars.yaml",
            )

        if mode == ExecutionMode.CONTAINER:
            run_cmd = self._build_container_test_cmd(ws, test_group)
        else:
            run_cmd = self._build_direct_test_cmd(ws, test_group)

        start = time.monotonic()
        r = self._executor.run(
            run_cmd,
            timeout=self._cfg.test_timeout_seconds,
            cwd=self._repo_dir,
        )
        duration = time.monotonic() - start

        if r.timed_out:
            outcome = Outcome.TIMEOUT
            error_msg = f"Test timed out after " f"{self._cfg.test_timeout_seconds}s"
        elif r.return_code == 0:
            outcome = Outcome.PASSED
            error_msg = ""
        else:
            outcome = Outcome.FAILED
            error_msg = f"Exit code {r.return_code}: " f"{r.stderr[-500:]}"

        report_path = self._find_report(ws)

        return TestResult(
            workspace_id=ws.workspace_id,
            test_group=test_group.value,
            outcome=outcome,
            duration_seconds=duration,
            stdout=r.stdout,
            stderr=r.stderr,
            error_message=error_msg,
            ansible_return_code=r.return_code,
            report_path=report_path,
        )

    def _build_direct_test_cmd(
        self,
        ws: WorkspaceCapability,
        test_group: TestGroup,
    ) -> str:
        """Build the direct playbook execution command.

        Exactly what the user runs after ``source .venv/bin/activate``.

        :param ws: Target workspace.
        :param test_group: Test group.
        :returns: Shell command string.
        :rtype: str
        """
        group_map = {
            TestGroup.DATABASE_HA: "HA_DB_HANA",
            TestGroup.CENTRAL_SERVICES_HA: "HA_SCS",
        }

        base_cmd = "source .venv/bin/activate && " "./scripts/sap_automation_qa.sh"

        if test_group == TestGroup.CONFIGURATION_CHECKS:
            return base_cmd

        group_flag = group_map.get(test_group, "")
        if group_flag:
            return f"{base_cmd} --test_groups={group_flag}"

        return base_cmd

    def _build_container_test_cmd(
        self,
        ws: WorkspaceCapability,
        test_group: TestGroup,
    ) -> str:
        """Build the container API-based test command.

        Uses the CLI wrapper exactly as documented:
        ``./scripts/sap_automation_qa.sh job create ...``

        :param ws: Target workspace.
        :param test_group: Test group.
        :returns: Shell command string.
        :rtype: str
        """
        return (
            f"./scripts/sap_automation_qa.sh job create "
            f"--workspace {ws.workspace_id} "
            f"--test-group {test_group.value}"
        )

    def _find_report(self, ws: WorkspaceCapability) -> str:
        """Locate the most recent HTML report for a workspace.

        :param ws: Target workspace.
        :returns: Remote path to report, or empty string.
        :rtype: str
        """
        qa_dir = f"{self._repo_dir}/WORKSPACES/SYSTEM/" f"{ws.workspace_id}/quality_assurance"
        r = self._executor.run(
            f"ls -t {qa_dir}/*.html 2>/dev/null | head -1",
            timeout=15,
        )
        if r.return_code == 0 and r.stdout.strip():
            return r.stdout.strip()
        return ""
