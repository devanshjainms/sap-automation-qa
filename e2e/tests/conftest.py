# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Pytest fixtures for E2E release validation.
"""

from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone
from typing import Generator
import pytest
from e2e.src.azure_deployer import AzureDeployer, DeployedVM
from e2e.src.config import Distro, E2EConfig
from e2e.src.models import E2ERunResult
from e2e.src.reporter import Reporter

logger = logging.getLogger(__name__)


@pytest.fixture(scope="session")
def e2e_config() -> E2EConfig:
    """Load E2E configuration from environment variables.

    :returns: Immutable E2E configuration.
    :rtype: E2EConfig
    """
    cfg = E2EConfig.from_env()
    logger.info(
        "E2E config loaded: %d distros, %d test groups",
        len(cfg.enabled_distros()),
        len(cfg.enabled_test_groups()),
    )
    return cfg


@pytest.fixture(scope="session")
def run_id() -> str:
    """Unique identifier for this E2E run.

    :returns: Short UUID string.
    :rtype: str
    """
    return uuid.uuid4().hex[:12]


@pytest.fixture(scope="session")
def azure_deployer(
    e2e_config: E2EConfig,
) -> Generator[AzureDeployer, None, None]:
    """Provision deployer VMs; unmount + delete on teardown.

    :param e2e_config: E2E configuration.
    :yields: Azure deployer with VMs provisioned.
    """
    deployer = AzureDeployer(e2e_config)

    logger.info(
        "Provisioning deployer VMs in %s...",
        e2e_config.azure_resource_group,
    )
    deployer.provision_all()

    yield deployer

    logger.info("Unmounting file shares on all VMs...")
    try:
        deployer.unmount_all()
    except Exception:
        logger.exception("Error during unmount_all")

    logger.info("Deleting deployer VMs...")
    try:
        deployer.delete_vms()
    except Exception:
        logger.exception("Error during delete_vms")

    logger.info("Tearing down deployer infrastructure...")
    deployer.teardown()


@pytest.fixture(scope="session")
def deployed_vms(
    azure_deployer: AzureDeployer,
) -> list[DeployedVM]:
    """List of successfully deployed VMs.

    :param azure_deployer: The provisioned deployer.
    :returns: List of deployed VMs.
    :rtype: list[DeployedVM]
    """
    return azure_deployer.deployed_vms


@pytest.fixture(scope="session")
def reporter(e2e_config: E2EConfig) -> Reporter:
    """Report generator instance.

    :param e2e_config: E2E configuration.
    :returns: Reporter instance.
    :rtype: Reporter
    """
    return Reporter(e2e_config.report_dir)


@pytest.fixture(scope="session")
def e2e_run_result(
    run_id: str,
    e2e_config: E2EConfig,
) -> E2ERunResult:
    """Shared run result accumulator.

    :param run_id: Unique run identifier.
    :param e2e_config: E2E configuration.
    :returns: Mutable run result to populate during tests.
    :rtype: E2ERunResult
    """
    return E2ERunResult(
        run_id=run_id,
        github_ref=e2e_config.github_ref,
    )


def _find_vm(vms: list[DeployedVM], distro: Distro) -> DeployedVM | None:
    """Find a VM by distro.

    :param vms: List of deployed VMs.
    :param distro: Target distro.
    :returns: Matching VM or None.
    :rtype: DeployedVM | None
    """
    for vm in vms:
        if vm.distro == distro:
            return vm
    return None


@pytest.fixture(scope="session", params=list(Distro))
def deployer_vm(
    request: pytest.FixtureRequest,
    deployed_vms: list[DeployedVM],
) -> DeployedVM:
    """Parametrized fixture yielding one VM per distro.

    :param request: Pytest request with distro param.
    :param deployed_vms: All deployed VMs.
    :returns: Deployed VM for this distro.
    :rtype: DeployedVM
    :raises pytest.skip: If distro was not deployed.
    """
    distro: Distro = request.param
    vm = _find_vm(deployed_vms, distro)
    if vm is None:
        pytest.skip(f"No VM deployed for distro {distro.value}")
    return vm
