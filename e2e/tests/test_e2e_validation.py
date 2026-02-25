# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
E2E release validation test suite.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
import pytest
from e2e.src.azure_deployer import DeployedVM
from e2e.src.config import (
    Distro,
    E2EConfig,
    ExecutionMode,
)
from e2e.src.models import (
    E2ERunResult,
    Outcome,
)
from e2e.src.orchestrator import TestOrchestrator
from e2e.src.remote_executor import RemoteExecutor
from e2e.src.reporter import Reporter
from e2e.src.workspace_discovery import (
    discover_workspaces,
)

logger = logging.getLogger(__name__)


class TestInfrastructure:
    """Validate that deployer VMs are reachable."""

    @pytest.mark.smoke
    def test_vm_deployed(
        self,
        deployer_vm: DeployedVM,
    ) -> None:
        """Verify the VM was provisioned with a private IP.

        :param deployer_vm: Parametrized per-distro VM.
        """
        assert deployer_vm.private_ip, f"No private IP for " f"{deployer_vm.distro.value} VM"

    @pytest.mark.smoke
    def test_ssh_reachable(
        self,
        deployer_vm: DeployedVM,
    ) -> None:
        """Verify SSH connectivity to the VM.

        :param deployer_vm: Parametrized per-distro VM.
        """
        executor = RemoteExecutor(deployer_vm)
        assert executor.wait_for_ssh(retries=20, delay=10), (
            f"SSH not reachable on " f"{deployer_vm.distro.value} " f"({deployer_vm.private_ip})"
        )

    @pytest.mark.smoke
    def test_os_matches_distro(
        self,
        deployer_vm: DeployedVM,
    ) -> None:
        """Verify the VM is running the expected OS family.

        :param deployer_vm: Parametrized per-distro VM.
        """
        executor = RemoteExecutor(deployer_vm)
        executor.wait_for_ssh()
        result = executor.run(
            "cat /etc/os-release | grep ^ID=",
            timeout=15,
        )
        assert result.return_code == 0
        os_id = result.stdout.strip().lower()
        distro = deployer_vm.distro

        expected_ids = {
            Distro.RHEL: ["rhel", "redhat"],
            Distro.SLES: ["sles", "suse"],
            Distro.UBUNTU: ["ubuntu"],
        }
        assert any(
            eid in os_id for eid in expected_ids[distro]
        ), f"Expected {distro.value}, got {os_id}"


class TestSetup:
    """Run setup.sh on each deployer exactly as documented."""

    @pytest.mark.lifecycle
    @pytest.mark.timeout(300)
    def test_git_install(
        self,
        deployer_vm: DeployedVM,
    ) -> None:
        """Step 1.2: Install git using distro package manager.

        From SETUP.MD:
        - Debian/Ubuntu: ``sudo apt-get install git``
        - RHEL: ``sudo yum install git``
        - SUSE: ``sudo zypper install git``

        :param deployer_vm: Parametrized per-distro VM.
        """
        executor = RemoteExecutor(deployer_vm)
        executor.wait_for_ssh()

        install_cmds = {
            Distro.RHEL: "sudo yum install -y git",
            Distro.SLES: "sudo zypper install -y git",
            Distro.UBUNTU: ("sudo apt-get update -y && " "sudo apt-get install -y git"),
        }
        cmd = install_cmds[deployer_vm.distro]
        result = executor.run(cmd, timeout=300)
        assert result.return_code == 0, (
            f"git install failed on {deployer_vm.distro.value}: " f"{result.stderr}"
        )

        verify = executor.run("git --version", timeout=10)
        assert verify.return_code == 0

    @pytest.mark.lifecycle
    @pytest.mark.timeout(300)
    def test_clone_repo(
        self,
        deployer_vm: DeployedVM,
        e2e_config: E2EConfig,
    ) -> None:
        """Step 1.3: Clone the repository.

        :param deployer_vm: Parametrized per-distro VM.
        :param e2e_config: E2E configuration.
        """
        executor = RemoteExecutor(deployer_vm)
        repo_dir = "/root/sap-automation-qa"

        cmd = (
            f"sudo rm -rf {repo_dir} && "
            f"sudo git clone {e2e_config.github_repo} "
            f"{repo_dir} && "
            f"cd {repo_dir} && "
            f"sudo git checkout {e2e_config.github_ref}"
        )
        result = executor.run(cmd, timeout=300)
        assert result.return_code == 0, (
            f"Clone failed on {deployer_vm.distro.value}: " f"{result.stderr}"
        )

        verify = executor.run(
            f"ls {repo_dir}/scripts/setup.sh "
            f"{repo_dir}/scripts/sap_automation_qa.sh "
            f"{repo_dir}/vars.yaml",
            timeout=10,
        )
        assert verify.return_code == 0, "Repository structure incomplete after clone"

    @pytest.mark.lifecycle
    @pytest.mark.timeout(900)
    def test_setup_sh(
        self,
        deployer_vm: DeployedVM,
        e2e_config: E2EConfig,
    ) -> None:
        """Step 1.4.1: Run ``./scripts/setup.sh``.

        :param deployer_vm: Parametrized per-distro VM.
        :param e2e_config: E2E configuration.
        """
        executor = RemoteExecutor(deployer_vm)
        repo_dir = "/root/sap-automation-qa"

        if ExecutionMode.CONTAINER in e2e_config.enabled_execution_modes():
            cmd = f"cd {repo_dir} && " "sudo ./scripts/setup.sh container start"
        else:
            cmd = f"cd {repo_dir} && " "sudo ./scripts/setup.sh"

        result = executor.run(cmd, timeout=900)
        assert result.return_code == 0, (
            f"setup.sh failed on {deployer_vm.distro.value}: " f"{result.stderr[-1000:]}"
        )

    @pytest.mark.lifecycle
    @pytest.mark.timeout(60)
    def test_venv_activation(
        self,
        deployer_vm: DeployedVM,
        e2e_config: E2EConfig,
    ) -> None:
        """Verify the venv can be activated and has key packages.

        :param deployer_vm: Parametrized per-distro VM.
        :param e2e_config: E2E configuration.
        """
        if ExecutionMode.CONTAINER in e2e_config.enabled_execution_modes():
            pytest.skip("Container mode — no local venv")

        executor = RemoteExecutor(deployer_vm)
        repo_dir = "/root/sap-automation-qa"

        result = executor.run(
            f"cd {repo_dir} && "
            "source .venv/bin/activate && "
            "python --version && "
            "ansible --version && "
            "az version",
            timeout=30,
        )
        assert result.return_code == 0, (
            f"venv activation failed on " f"{deployer_vm.distro.value}: {result.stderr}"
        )

    @pytest.mark.lifecycle
    @pytest.mark.timeout(60)
    def test_container_health(
        self,
        deployer_vm: DeployedVM,
        e2e_config: E2EConfig,
    ) -> None:
        """Verify container health endpoint (container mode).

        :param deployer_vm: Parametrized per-distro VM.
        :param e2e_config: E2E configuration.
        """
        if ExecutionMode.CONTAINER not in e2e_config.enabled_execution_modes():
            pytest.skip("Local mode — no container")

        executor = RemoteExecutor(deployer_vm)

        result = executor.run(
            "curl -sf http://localhost:8000/healthz",
            timeout=30,
        )
        assert result.return_code == 0, (
            f"Container health check failed on " f"{deployer_vm.distro.value}: {result.stderr}"
        )
        assert '"healthy"' in result.stdout


class TestWorkspaceDiscovery:
    """Discover and classify workspaces on each deployer."""

    @pytest.mark.workspace
    @pytest.mark.timeout(120)
    def test_discover_workspaces(
        self,
        deployer_vm: DeployedVM,
        e2e_config: E2EConfig,
    ) -> None:
        """Verify workspaces are discoverable after setup.

        :param deployer_vm: Parametrized per-distro VM.
        :param e2e_config: E2E configuration.
        """
        executor = RemoteExecutor(deployer_vm)
        repo_dir = "/root/sap-automation-qa"

        workspaces = discover_workspaces(executor, e2e_config, repo_dir)

        if e2e_config.workspace_configs:
            found_ids = {w.workspace_id for w in workspaces}
            for expected in e2e_config.workspace_configs:
                assert expected in found_ids, (
                    f"Expected workspace '{expected}' not found "
                    f"on {deployer_vm.distro.value}. "
                    f"Found: {found_ids}"
                )

        logger.info(
            "Discovered %d workspaces on %s: %s",
            len(workspaces),
            deployer_vm.distro.value,
            [w.workspace_id for w in workspaces],
        )


class TestEndToEnd:
    """Run the complete test orchestration on each deployer."""

    @pytest.mark.lifecycle
    @pytest.mark.slow
    @pytest.mark.timeout(7200)
    def test_full_orchestration(
        self,
        deployer_vm: DeployedVM,
        e2e_config: E2EConfig,
        e2e_run_result: E2ERunResult,
        reporter: Reporter,
    ) -> None:
        """Execute the full user workflow and validate results.

        :param deployer_vm: Parametrized per-distro VM.
        :param e2e_config: E2E configuration.
        :param e2e_run_result: Shared result accumulator.
        :param reporter: Report generator.
        """
        modes = e2e_config.enabled_execution_modes()
        orchestrator = TestOrchestrator(deployer_vm, e2e_config)

        for mode in modes:
            deployer_result = orchestrator.run(mode)
            e2e_run_result.deployer_results.append(deployer_result)

            logger.info(
                "%s/%s deployer: setup=%s, " "workspaces=%d, tests=%d/%d passed",
                deployer_vm.distro.value,
                mode.value,
                deployer_result.setup_outcome.value,
                len(deployer_result.workspaces_discovered),
                deployer_result.passed,
                deployer_result.total,
            )

            assert deployer_result.setup_outcome == Outcome.PASSED, (
                f"Setup failed on "
                f"{deployer_vm.distro.value}/{mode.value}"
                f": {deployer_result.setup_stderr[-500:]}"
            )

            if not e2e_config.dry_run:
                assert deployer_result.total > 0, (
                    f"No tests executed on " f"{deployer_vm.distro.value}" f"/{mode.value}"
                )
                assert deployer_result.all_passed, (
                    f"{deployer_result.failed} failed, "
                    f"{deployer_result.errors} errors on "
                    f"{deployer_vm.distro.value}"
                    f"/{mode.value}"
                )


class TestReporting:
    """Generate reports after all deployers complete."""

    @pytest.mark.lifecycle
    def test_generate_reports(
        self,
        e2e_run_result: E2ERunResult,
        reporter: Reporter,
        e2e_config: E2EConfig,
    ) -> None:
        """Generate HTML, JUnit, and GitHub summary reports.

        :param e2e_run_result: Accumulated results.
        :param reporter: Report generator.
        :param e2e_config: E2E configuration.
        """
        e2e_run_result.finished_at = datetime.now(timezone.utc)

        paths = reporter.generate_all(e2e_run_result)
        assert "html" in paths
        assert "junit" in paths

        logger.info(e2e_run_result.summary_line())

    @pytest.mark.lifecycle
    def test_overall_pass(
        self,
        e2e_run_result: E2ERunResult,
    ) -> None:
        """Final gate: assert the entire E2E run passed.

        :param e2e_run_result: Accumulated results.
        """
        assert e2e_run_result.all_passed, e2e_run_result.summary_line()
