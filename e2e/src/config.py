# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
E2E Release Validation — configuration & environment bindings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum


class Distro(str, Enum):
    """Supported management-server Linux distributions."""

    RHEL = "rhel"
    SLES = "sles"
    UBUNTU = "ubuntu"


class TestGroup(str, Enum):
    """Mirror of ``TEST_GROUP_PLAYBOOKS`` in the framework executor."""

    CONFIGURATION_CHECKS = "ConfigurationChecks"
    DATABASE_HA = "DatabaseHighAvailability"
    CENTRAL_SERVICES_HA = "CentralServicesHighAvailability"


class ExecutionMode(str, Enum):
    """How tests are executed on the deployer VM."""

    LOCAL = "local"
    CONTAINER = "container"


_REQUIRED_FIELDS: tuple[str, ...] = (
    "azure_subscription_id",
    "vnet_subnet_id",
    "vm_admin_password",
    "user_assigned_identity_id",
    "storage_account_name",
)


@dataclass(frozen=True, slots=True)
class E2EConfig:
    """Immutable configuration resolved once at session start.

    Required fields have **no default** — callers must supply
    them explicitly (typically via ``from_env()``).  Optional
    fields carry sensible defaults that rarely need overriding.

    """

    azure_subscription_id: str
    vnet_subnet_id: str
    vm_admin_password: str
    user_assigned_identity_id: str
    storage_account_name: str

    azure_resource_group: str = "rg-sap-qa-e2e"
    azure_location: str = "swedencentral"
    file_share_name: str = "workspaces"
    github_repo: str = "https://github.com/Azure/sap-automation-qa.git"
    github_ref: str = "main"
    vm_size: str = "Standard_D4s_v5"
    vm_admin_username: str = "azureadm"
    distros: list[str] = field(default_factory=lambda: [d.value for d in Distro])
    execution_modes: list[str] = field(default_factory=lambda: [m.value for m in ExecutionMode])

    deploy_timeout_seconds: int = 900
    test_timeout_seconds: int = 7200
    health_retries: int = 30
    health_retry_delay: int = 20
    report_dir: str = "e2e/reports"

    authentication_type: str = "VMPASSWORD"

    skip_teardown: bool = False
    dry_run: bool = False

    test_groups: list[str] = field(default_factory=list)
    workspace_configs: list[str] = field(default_factory=list)

    telemetry_enabled: bool = False
    adx_cluster_fqdn: str = ""
    adx_database_name: str = ""
    laws_workspace_id: str = ""
    laws_resource_group: str = ""
    laws_workspace_name: str = ""
    telemetry_table_name: str = "SAP_AUTOMATION_QA"

    def __post_init__(self) -> None:
        """Validate required fields are non-empty."""
        missing = [f for f in _REQUIRED_FIELDS if not getattr(self, f)]
        if missing:
            env_hint = ", ".join(f"E2E_{f.upper()}" for f in missing)
            raise ValueError(
                "Missing required E2E config: "
                f"{', '.join(missing)}.  "
                f"Set env vars: {env_hint}"
            )

    @classmethod
    def from_env(cls) -> E2EConfig:
        """Build config from environment variables.

        :returns: Validated ``E2EConfig``.
        :rtype: E2EConfig
        :raises ValueError: If required env vars are missing.
        """
        raw_groups = os.getenv("E2E_TEST_GROUPS", "")
        groups = [g.strip() for g in raw_groups.split(",") if g.strip()]

        raw_distros = os.getenv("E2E_DISTROS", "")
        distros = [d.strip() for d in raw_distros.split(",") if d.strip()] or [
            d.value for d in Distro
        ]

        raw_workspaces = os.getenv("E2E_WORKSPACE_CONFIGS", "")
        workspaces = [w.strip() for w in raw_workspaces.split(",") if w.strip()]

        raw_modes = os.getenv("E2E_EXECUTION_MODES", "")
        modes = [m.strip() for m in raw_modes.split(",") if m.strip()] or [
            m.value for m in ExecutionMode
        ]

        return cls(
            azure_subscription_id=os.getenv("E2E_AZURE_SUBSCRIPTION_ID", ""),
            vnet_subnet_id=os.getenv("E2E_VNET_SUBNET_ID", ""),
            vm_admin_password=os.getenv("E2E_VM_ADMIN_PASSWORD", ""),
            user_assigned_identity_id=os.getenv("E2E_USER_ASSIGNED_IDENTITY_ID", ""),
            storage_account_name=os.getenv("E2E_STORAGE_ACCOUNT_NAME", ""),
            azure_resource_group=os.getenv(
                "E2E_AZURE_RESOURCE_GROUP",
                "rg-sap-qa-e2e",
            ),
            azure_location=os.getenv("E2E_AZURE_LOCATION", "swedencentral"),
            file_share_name=os.getenv("E2E_FILE_SHARE_NAME", "workspaces"),
            github_repo=os.getenv(
                "E2E_GITHUB_REPO",
                "https://github.com/Azure/" "sap-automation-qa.git",
            ),
            github_ref=os.getenv("E2E_GITHUB_REF", "main"),
            vm_size=os.getenv("E2E_VM_SIZE", "Standard_D4s_v5"),
            vm_admin_username=os.getenv("E2E_VM_ADMIN_USERNAME", "azureadm"),
            distros=distros,
            execution_modes=modes,
            deploy_timeout_seconds=int(os.getenv("E2E_DEPLOY_TIMEOUT", "900")),
            test_timeout_seconds=int(os.getenv("E2E_TEST_TIMEOUT", "7200")),
            health_retries=int(os.getenv("E2E_HEALTH_RETRIES", "30")),
            health_retry_delay=int(os.getenv("E2E_HEALTH_RETRY_DELAY", "20")),
            report_dir=os.getenv("E2E_REPORT_DIR", "e2e/reports"),
            skip_teardown=os.getenv("E2E_SKIP_TEARDOWN", "").lower() in ("1", "true", "yes"),
            dry_run=os.getenv("E2E_DRY_RUN", "").lower() in ("1", "true", "yes"),
            authentication_type=os.getenv(
                "E2E_AUTHENTICATION_TYPE",
                "VMPASSWORD",
            ),
            test_groups=groups,
            workspace_configs=workspaces,
            telemetry_enabled=os.getenv("E2E_TELEMETRY_ENABLED", "").lower()
            in ("1", "true", "yes"),
            adx_cluster_fqdn=os.getenv("E2E_ADX_CLUSTER_FQDN", ""),
            adx_database_name=os.getenv("E2E_ADX_DATABASE_NAME", ""),
            laws_workspace_id=os.getenv("E2E_LAWS_WORKSPACE_ID", ""),
            laws_resource_group=os.getenv("E2E_LAWS_RESOURCE_GROUP", ""),
            laws_workspace_name=os.getenv("E2E_LAWS_WORKSPACE_NAME", ""),
            telemetry_table_name=os.getenv(
                "E2E_TELEMETRY_TABLE_NAME",
                "SAP_AUTOMATION_QA",
            ),
        )

    def enabled_distros(self) -> list[Distro]:
        """Return the distros the user asked for, or all if unset.

        :returns: List of enabled ``Distro`` enums.
        :rtype: list[Distro]
        """
        out: list[Distro] = []
        for name in self.distros:
            try:
                out.append(Distro(name.lower()))
            except ValueError:
                pass
        return out or list(Distro)

    def enabled_test_groups(self) -> list[TestGroup]:
        """Return the test groups the user asked for, or all if unset.

        :returns: List of enabled ``TestGroup`` enums.
        :rtype: list[TestGroup]
        """
        if not self.test_groups:
            return list(TestGroup)
        out: list[TestGroup] = []
        for name in self.test_groups:
            try:
                out.append(TestGroup(name))
            except ValueError:
                pass
        return out or list(TestGroup)

    def enabled_execution_modes(self) -> list[ExecutionMode]:
        """Return the execution modes to test.

        :returns: List of enabled ``ExecutionMode`` enums.
        :rtype: list[ExecutionMode]
        """
        out: list[ExecutionMode] = []
        for name in self.execution_modes:
            try:
                out.append(ExecutionMode(name.lower()))
            except ValueError:
                pass
        return out or list(ExecutionMode)
