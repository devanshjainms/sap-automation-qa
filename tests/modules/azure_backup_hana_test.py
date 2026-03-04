# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Unit tests for the azure_backup_hana module.
"""

from datetime import datetime
from types import SimpleNamespace
import pytest
from src.modules.azure_backup_hana import AzureBackupHana, run_module
from src.module_utils.enums import TestStatus


def _make_protected_item(
    friendly_name: str = "SYSTEMDB",
    server_name: str = "hanavm01",
    parent_name: str = "H05",
    health_status: str | None = "Healthy",
    protection_status: str = "Protected",
    last_backup_time: datetime | None = None,
    policy_name: str = "daily-policy",
    container_name: str = "VMAppContainer;Compute;rg;hanavm01",
    item_name: str = "saphanadatabase;h05;systemdb",
) -> SimpleNamespace:
    """Build a fake ``ProtectedItemResource`` for testing."""
    return SimpleNamespace(
        name=item_name,
        container_name=container_name,
        properties=SimpleNamespace(
            friendly_name=friendly_name,
            server_name=server_name,
            parent_name=parent_name,
            health_status=health_status,
            protection_status=protection_status,
            last_backup_time=last_backup_time or datetime(2026, 3, 1, 12, 0),
            policy_name=policy_name,
            container_name=container_name,
        ),
    )


def _make_recovery_point(
    rp_id: str = "/subscriptions/sub/resourceGroups/rg/"
    "providers/Microsoft.RecoveryServices/"
    "vaults/vault/backupFabrics/Azure/"
    "protectionContainers/ctr/"
    "protectedItems/item/recoveryPoints/rp123",
    rp_time: datetime | None = None,
    rp_type: str = "Full",
) -> SimpleNamespace:
    """Build a fake ``RecoveryPointResource`` for testing."""
    return SimpleNamespace(
        id=rp_id,
        properties=SimpleNamespace(
            recovery_point_time=rp_time or datetime(2026, 3, 1, 10, 0),
            type=rp_type,
        ),
    )


def _make_job(status: str = "Completed") -> SimpleNamespace:
    """Build a fake ``JobResource`` for testing."""
    return SimpleNamespace(
        properties=SimpleNamespace(status=status),
    )


def _make_poller(
    job_id: str = "job-abc-123",
    header_key: str = "azure-asyncoperation",
) -> SimpleNamespace:
    """Build a fake LRO poller with headers containing a job ID."""
    url = (
        f"https://management.azure.com/subscriptions/sub/"
        f"resourceGroups/rg/providers/Microsoft.RecoveryServices/"
        f"operationResults/{job_id}?api-version=2024-01-01"
    )
    return SimpleNamespace(
        initial_response=lambda: SimpleNamespace(
            http_response=SimpleNamespace(headers={header_key: url}),
        ),
    )


@pytest.fixture
def mock_client(mocker):
    """Return a ``mocker.MagicMock`` standing in for ``RecoveryServicesBackupClient``."""
    return mocker.MagicMock()


@pytest.fixture
def backup(mock_client, mocker):
    """Create an ``AzureBackupHana`` instance with the SDK client pre-injected."""
    mocker.patch(
        "src.modules.azure_backup_hana.ManagedIdentityCredential",
    )
    instance = AzureBackupHana(
        vault_resource_id=(
            "/subscriptions/sub-123"
            "/resourceGroups/test-rg"
            "/providers/Microsoft.RecoveryServices"
            "/vaults/test-vault"
        ),
        subscription_id="sub-123",
        msi_client_id="msi-abc",
        database_sid="H05",
        poll_interval=0,
        poll_timeout=5,
    )
    instance._client = mock_client
    return instance


class TestAzureBackupHanaInit:
    """Tests for ``AzureBackupHana`` initialisation."""

    def test_default_result_keys(self, backup):
        """Result dict contains required keys after init."""
        for key in (
            "protected_items",
            "restore_points",
            "restore_job",
            "start",
            "end",
        ):
            assert key in backup.result

    def test_initial_values(self, backup):
        """Attributes correctly stored from constructor."""
        assert backup.vault_name == "test-vault"
        assert backup.vault_resource_group == "test-rg"
        assert backup.subscription_id == "sub-123"
        assert backup.database_sid == "H05"
        assert backup.poll_interval == 0
        assert backup.poll_timeout == 5

    def test_vault_resource_id_stored(self, backup):
        """Full resource ID is stored on the instance."""
        assert "Microsoft.RecoveryServices/vaults/test-vault" in (
            backup.vault_resource_id
        )

    def test_result_start_is_iso_timestamp(self, backup):
        """The start timestamp must be a valid ISO-8601 string."""
        datetime.fromisoformat(backup.result["start"])

    def test_returns_cached_client(self, backup, mock_client):
        """When ``_client`` is set, the property should return it directly."""
        assert backup.client is mock_client

    def test_creates_client_when_none(self, mocker):
        """Client is created via SDK when ``_client`` is ``None``."""
        mock_cred = mocker.patch(
            "src.modules.azure_backup_hana.ManagedIdentityCredential",
        )
        mock_cls = mocker.patch(
            "src.modules.azure_backup_hana.RecoveryServicesBackupClient",
        )
        instance = AzureBackupHana(
            vault_resource_id=(
                "/subscriptions/sub"
                "/resourceGroups/rg"
                "/providers/Microsoft.RecoveryServices"
                "/vaults/v"
            ),
            subscription_id="sub",
            msi_client_id="msi",
        )
        instance._client = None
        _ = instance.client
        mock_cred.assert_called_once_with(client_id="msi")
        mock_cls.assert_called_once_with(
            credential=mock_cred.return_value,
            subscription_id="sub",
        )

    def test_creates_system_mi_when_no_client_id(self, mocker):
        """System-assigned MI used when ``msi_client_id`` is empty."""
        mock_cred = mocker.patch(
            "src.modules.azure_backup_hana.ManagedIdentityCredential",
        )
        mocker.patch(
            "src.modules.azure_backup_hana.RecoveryServicesBackupClient",
        )
        instance = AzureBackupHana(
            vault_resource_id=(
                "/subscriptions/sub"
                "/resourceGroups/rg"
                "/providers/Microsoft.RecoveryServices"
                "/vaults/v"
            ),
            subscription_id="sub",
            msi_client_id="",
        )
        instance._client = None
        _ = instance.client
        mock_cred.assert_called_once_with()

    def test_raises_runtime_error_on_auth_failure(self, mocker):
        """``RuntimeError`` raised when credential creation fails."""
        mocker.patch(
            "src.modules.azure_backup_hana.ManagedIdentityCredential",
            side_effect=Exception("auth boom"),
        )
        instance = AzureBackupHana(
            vault_resource_id=(
                "/subscriptions/sub"
                "/resourceGroups/rg"
                "/providers/Microsoft.RecoveryServices"
                "/vaults/v"
            ),
            subscription_id="sub",
        )
        instance._client = None
        with pytest.raises(RuntimeError, match="auth boom"):
            _ = instance.client


class TestStaticHelpers:
    """Tests for static / private utility methods."""

    @pytest.mark.parametrize(
        "rp_id, expected",
        [
            ("/subs/rg/rp123", "rp123"),
            ("single", "single"),
            ("", ""),
        ],
    )
    def test_rp_name_from_id(self, rp_id, expected):
        """Last ARM path segment extracted correctly."""
        assert AzureBackupHana._rp_name_from_id(rp_id) == expected

    def test_build_container_id(self, backup):
        """ARM resource ID built with correct format."""
        cid = backup._build_container_id("myvm", "myrg")
        assert cid == (
            "/subscriptions/sub-123"
            "/resourceGroups/myrg"
            "/providers/Microsoft.Compute"
            "/virtualMachines/myvm"
        )

    def test_extract_item_info(self):
        """Item info dict populated from SDK object."""
        item = _make_protected_item(friendly_name="DB01")
        info = AzureBackupHana._extract_item_info(item)
        assert info["friendly_name"] == "DB01"
        assert info["health_status"] == "Healthy"
        assert info["item_name"] == "saphanadatabase;h05;systemdb"

    def test_extract_item_info_none_health(self):
        """None health_status falls back to 'Unknown'."""
        item = _make_protected_item(health_status=None)
        info = AzureBackupHana._extract_item_info(item)
        assert info["health_status"] == "Unknown"

    def test_extract_job_id_from_async_header(self):
        """Job ID parsed from ``azure-asyncoperation`` header."""
        poller = _make_poller(
            job_id="j-999",
            header_key="azure-asyncoperation",
        )
        assert AzureBackupHana._extract_job_id_from_poller(poller) == "j-999"

    def test_extract_job_id_from_location_header(self):
        """Job ID parsed from ``location`` header
        when async header is absent."""
        poller = _make_poller(
            job_id="j-loc",
            header_key="location",
        )
        assert AzureBackupHana._extract_job_id_from_poller(poller) == "j-loc"

    def test_extract_job_id_empty_on_exception(self):
        """Empty string returned when poller raises."""

        def _raise(*_a, **_kw):
            raise RuntimeError("boom")

        poller = SimpleNamespace(initial_response=_raise)
        assert AzureBackupHana._extract_job_id_from_poller(poller) == ""

    def test_extract_job_id_empty_when_no_headers(self):
        """Empty string when headers contain no matching URL."""
        poller = SimpleNamespace(
            initial_response=lambda: SimpleNamespace(
                http_response=SimpleNamespace(headers={}),
            ),
        )
        assert AzureBackupHana._extract_job_id_from_poller(poller) == ""

    def test_all_healthy(self, backup, mock_client):
        """SUCCESS when every item is healthy."""
        mock_client.backup_protected_items.list.return_value = [
            _make_protected_item(friendly_name="DB1"),
            _make_protected_item(friendly_name="DB2"),
        ]
        result = backup.discover_protected_items()

        assert result["status"] == TestStatus.SUCCESS.value
        assert len(result["protected_items"]) == 2
        assert "healthy" in result["message"].lower()
        assert result["end"] is not None

    def test_unhealthy_items_give_warning(self, backup, mock_client):
        """WARNING when at least one item is unhealthy."""
        mock_client.backup_protected_items.list.return_value = [
            _make_protected_item(health_status="Healthy"),
            _make_protected_item(health_status="Unhealthy"),
        ]
        result = backup.discover_protected_items()

        assert result["status"] == TestStatus.WARNING.value
        assert "1 unhealthy" in result["message"]

    def test_empty_vault(self, backup, mock_client):
        """SUCCESS with zero items when vault is empty."""
        mock_client.backup_protected_items.list.return_value = []
        result = backup.discover_protected_items()

        assert result["status"] == TestStatus.SUCCESS.value
        assert result["protected_items"] == []

    def test_last_backup_time_none(self, backup, mock_client):
        """Empty string when last_backup_time is ``None``."""
        item = _make_protected_item()
        item.properties.last_backup_time = None
        mock_client.backup_protected_items.list.return_value = [item]
        result = backup.discover_protected_items()
        assert result["protected_items"][0]["last_backup_time"] == ""

    def test_all_items_have_restore_points(self, backup, mock_client):
        """SUCCESS when every item has at least one RP."""
        mock_client.backup_protected_items.list.return_value = [
            _make_protected_item(),
        ]
        mock_client.recovery_points.list.return_value = [
            _make_recovery_point(),
        ]
        result = backup.check_restore_points()

        assert result["status"] == TestStatus.SUCCESS.value
        assert len(result["restore_points"]) == 1
        assert result["restore_points"][0]["recovery_point_count"] == 1

    def test_missing_restore_points_give_warning(
        self,
        backup,
        mock_client,
    ):
        """WARNING when an item has no recovery points."""
        mock_client.backup_protected_items.list.return_value = [
            _make_protected_item(),
        ]
        mock_client.recovery_points.list.return_value = []

        result = backup.check_restore_points()

        assert result["status"] == TestStatus.WARNING.value
        assert "no recovery points" in result["message"]

    def test_original_workload_restore(self, backup, mock_client):
        """SUCCESS for in-place (original workload) restore."""
        mock_client.recovery_points.list.return_value = [
            _make_recovery_point(),
        ]
        mock_client.restores.begin_trigger.return_value = _make_poller(
            job_id="job-111",
        )

        result = backup.restore_to_database(
            container_name="ctr",
            item_name="item",
        )

        assert result["status"] == TestStatus.SUCCESS.value
        assert result["restore_job"]["job_id"] == "job-111"
        assert result["restore_job"]["restore_mode"] == ("OriginalWorkloadRestore")

    def test_alternate_workload_restore(self, backup, mock_client):
        """SUCCESS for cross-VM (alternate workload) restore."""
        mock_client.recovery_points.list.return_value = [
            _make_recovery_point(),
        ]
        mock_client.restores.begin_trigger.return_value = _make_poller(
            job_id="job-222",
        )

        result = backup.restore_to_database(
            container_name="ctr",
            item_name="item",
            target_container_name="target-ctr",
            target_database_name="target-db",
        )

        assert result["status"] == TestStatus.SUCCESS.value
        assert result["restore_job"]["restore_mode"] == ("AlternateWorkloadRestore")

    def test_no_recovery_point_returns_error_no_recovery(
        self,
        backup,
        mock_client,
    ):
        """ERROR when no recovery point exists."""
        mock_client.recovery_points.list.return_value = []

        result = backup.restore_to_database(
            container_name="ctr",
            item_name="item",
        )

        assert result["status"] == TestStatus.ERROR.value
        assert "recovery point" in result["message"].lower()

    def test_sdk_exception_handled_sdk_ex_1(self, backup, mock_client):
        """handle_error called on SDK exception."""
        mock_client.recovery_points.list.side_effect = RuntimeError("restore fail")

        result = backup.restore_to_database(
            container_name="ctr",
            item_name="item",
        )

        assert result["status"] == TestStatus.ERROR.value

    def test_restore_as_files_success(self, backup, mock_client):
        """SUCCESS when restore-as-files triggers correctly."""
        mock_client.recovery_points.list.return_value = [
            _make_recovery_point(),
        ]
        mock_client.restores.begin_trigger.return_value = _make_poller(
            job_id="job-fs-1",
        )

        result = backup.restore_to_filesystem(
            container_name="ctr",
            item_name="item",
            target_filesystem_path="/backup/restore",
        )

        assert result["status"] == TestStatus.SUCCESS.value
        assert result["restore_job"]["restore_mode"] == "RestoreAsFiles"
        assert result["restore_job"]["target_path"] == "/backup/restore"

    def test_cross_vm_filesystem_restore(self, backup, mock_client):
        """SUCCESS with target VM parameters set."""
        mock_client.recovery_points.list.return_value = [
            _make_recovery_point(),
        ]
        mock_client.restores.begin_trigger.return_value = _make_poller(
            job_id="job-fs-2",
        )

        result = backup.restore_to_filesystem(
            container_name="ctr",
            item_name="item",
            target_filesystem_path="/backup/restore",
            target_vm_name="targetvm",
            target_vm_resource_group="targetrg",
        )

        assert result["status"] == TestStatus.SUCCESS.value

    def test_no_recovery_point_returns_error(
        self,
        backup,
        mock_client,
    ):
        """ERROR when no recovery point exists."""
        mock_client.recovery_points.list.return_value = []

        result = backup.restore_to_filesystem(
            container_name="ctr",
            item_name="item",
            target_filesystem_path="/backup/restore",
        )

        assert result["status"] == TestStatus.ERROR.value

    def test_sdk_exception_handled_sdk_ex(self, backup, mock_client):
        """handle_error called on SDK exception."""
        mock_client.recovery_points.list.side_effect = RuntimeError("fs fail")

        result = backup.restore_to_filesystem(
            container_name="ctr",
            item_name="item",
            target_filesystem_path="/tmp",
        )

        assert result["status"] == TestStatus.ERROR.value

    def test_completed_job(self, backup, mock_client):
        """SUCCESS when job completes normally."""
        mock_client.job_details.get.return_value = _make_job("Completed")

        result = backup.check_restore_job(restore_job_id="j-1")

        assert result["status"] == TestStatus.SUCCESS.value
        assert result["restore_job"]["job_id"] == "j-1"
        assert "successfully" in result["message"]

    def test_completed_with_warnings(self, backup, mock_client):
        """WARNING when job status is ``CompletedWithWarnings``."""
        mock_client.job_details.get.return_value = _make_job(
            "CompletedWithWarnings",
        )

        result = backup.check_restore_job(restore_job_id="j-2")

        assert result["status"] == TestStatus.WARNING.value
        assert "warnings" in result["message"]

    def test_failed_job(self, backup, mock_client):
        """ERROR when job status is ``Failed``."""
        mock_client.job_details.get.return_value = _make_job("Failed")

        result = backup.check_restore_job(restore_job_id="j-3")

        assert result["status"] == TestStatus.ERROR.value
        assert "Failed" in result["message"]

    def test_cancelled_job(self, backup, mock_client):
        """ERROR when job status is ``Cancelled``."""
        mock_client.job_details.get.return_value = _make_job("Cancelled")

        result = backup.check_restore_job(restore_job_id="j-4")

        assert result["status"] == TestStatus.ERROR.value

    def test_timeout(self, mock_client, mocker):
        """ERROR when polling exceeds ``poll_timeout``."""
        mocker.patch(
            "src.modules.azure_backup_hana.ManagedIdentityCredential",
        )
        instance = AzureBackupHana(
            vault_resource_id=(
                "/subscriptions/sub"
                "/resourceGroups/rg"
                "/providers/Microsoft.RecoveryServices"
                "/vaults/v"
            ),
            subscription_id="sub",
            poll_interval=1,
            poll_timeout=1,
        )
        instance._client = mock_client
        mock_client.job_details.get.return_value = _make_job("InProgress")
        mocker.patch("src.modules.azure_backup_hana.time.sleep")

        result = instance.check_restore_job(restore_job_id="j-5")

        assert result["status"] == TestStatus.ERROR.value
        assert "timed out" in result["message"]

    def test_sdk_exception_handled(self, backup, mock_client):
        """handle_error called on SDK exception."""
        mock_client.job_details.get.side_effect = RuntimeError("poll fail")

        result = backup.check_restore_job(restore_job_id="j-6")

        assert result["status"] == TestStatus.ERROR.value


class TestSetJobResultStatus:
    """Tests for ``_set_job_result_status`` helper."""

    @pytest.mark.parametrize(
        "status, expected_test_status",
        [
            ("Completed", TestStatus.SUCCESS.value),
            ("CompletedWithWarnings", TestStatus.WARNING.value),
            ("Failed", TestStatus.ERROR.value),
        ],
    )
    def test_status_mapping(
        self,
        backup,
        status,
        expected_test_status,
    ):
        """Correct ``TestStatus`` set for each terminal status."""
        backup._set_job_result_status("j-1", status, 10)
        assert backup.result["status"] == expected_test_status

    def test_timeout_mapping(self, backup):
        """ERROR with timeout message when elapsed >= poll_timeout."""
        backup._set_job_result_status(
            "j-1",
            "InProgress",
            backup.poll_timeout,
        )
        assert backup.result["status"] == TestStatus.ERROR.value
        assert "timed out" in backup.result["message"]

    def test_returns_first_rp_id(self, backup, mock_client):
        """First recovery point ID returned when list is non-empty."""
        mock_client.recovery_points.list.return_value = [
            _make_recovery_point(rp_id="/rp/first"),
            _make_recovery_point(rp_id="/rp/second"),
        ]
        rp_id = backup._resolve_recovery_point("ctr", "item")
        assert rp_id == "/rp/first"

    def test_returns_empty_when_no_rps(self, backup, mock_client):
        """Empty string returned when no recovery points exist."""
        mock_client.recovery_points.list.return_value = []
        rp_id = backup._resolve_recovery_point("ctr", "item")
        assert rp_id == ""

    def test_logs_pit_when_provided(self, backup, mock_client):
        """PIT timestamp is logged when provided."""
        mock_client.recovery_points.list.return_value = [
            _make_recovery_point(rp_id="/rp/first"),
        ]
        backup._resolve_recovery_point(
            "ctr",
            "item",
            "2026-03-01T00:00:00",
        )
        assert any("point-in-time" in log.lower() for log in backup.result["logs"])

    def test_original_restore_has_no_target_info(self, backup):
        """``target_info`` is ``None`` for original restore."""
        req = backup._build_workload_restore(
            rp_id="/rp/1",
            restore_mode="OriginalWorkloadRestore",
        )
        assert req.properties.target_info is None

    def test_alternate_restore_has_target_info(self, backup):
        """``target_info`` populated for alternate restore."""
        req = backup._build_workload_restore(
            rp_id="/rp/1",
            restore_mode="AlternateWorkloadRestore",
            target_container_name="ctr",
            target_database_name="db",
        )
        assert req.properties.target_info is not None
        assert req.properties.target_info.container_id == "ctr"
        assert req.properties.target_info.database_name == "db"

    def test_discover_dispatches_correctly(self, monkeypatch, mocker):
        """``run_module`` dispatches discover_protected_items."""
        exit_kwargs = {}

        class FakeModule:
            def __init__(self, *args, **kwargs):
                self.params = {
                    "operation": "discover_protected_items",
                    "subscription_id": "sub",
                    "msi_client_id": "",
                    "vault_resource_id": (
                        "/subscriptions/sub"
                        "/resourceGroups/rg"
                        "/providers/Microsoft.RecoveryServices"
                        "/vaults/v"
                    ),
                    "database_sid": "",
                    "container_name": "",
                    "item_name": "",
                    "restore_point_time": "",
                    "target_container_name": "",
                    "target_database_name": "",
                    "target_filesystem_path": "",
                    "target_vm_name": "",
                    "target_vm_resource_group": "",
                    "restore_job_id": "",
                    "poll_interval_seconds": 0,
                    "poll_timeout_seconds": 0,
                }

            def exit_json(self, **kwargs):
                nonlocal exit_kwargs
                exit_kwargs = kwargs

            def fail_json(self, **kwargs):
                nonlocal exit_kwargs
                exit_kwargs = kwargs

        monkeypatch.setattr(
            "src.modules.azure_backup_hana.AnsibleModule",
            FakeModule,
        )

        mock_client = mocker.MagicMock()
        mock_client.backup_protected_items.list.return_value = []
        mocker.patch(
            "src.modules.azure_backup_hana.ManagedIdentityCredential",
        )
        mocker.patch(
            "src.modules.azure_backup_hana.RecoveryServicesBackupClient",
            return_value=mock_client,
        )

        run_module()

        assert "status" in exit_kwargs

    def test_error_result_calls_fail_json(self, monkeypatch, mocker):
        """``fail_json`` called when operation returns ERROR status."""
        fail_kwargs = {}

        class FakeModule:
            def __init__(self, *args, **kwargs):
                self.params = {
                    "operation": "discover_protected_items",
                    "subscription_id": "sub",
                    "msi_client_id": "",
                    "vault_resource_id": (
                        "/subscriptions/sub"
                        "/resourceGroups/rg"
                        "/providers/Microsoft.RecoveryServices"
                        "/vaults/v"
                    ),
                    "database_sid": "",
                    "container_name": "",
                    "item_name": "",
                    "restore_point_time": "",
                    "target_container_name": "",
                    "target_database_name": "",
                    "target_filesystem_path": "",
                    "target_vm_name": "",
                    "target_vm_resource_group": "",
                    "restore_job_id": "",
                    "poll_interval_seconds": 0,
                    "poll_timeout_seconds": 0,
                }

            def exit_json(self, **kwargs):
                pass

            def fail_json(self, **kwargs):
                nonlocal fail_kwargs
                fail_kwargs = kwargs

        monkeypatch.setattr(
            "src.modules.azure_backup_hana.AnsibleModule",
            FakeModule,
        )

        mock_client = mocker.MagicMock()
        mock_client.backup_protected_items.list.side_effect = RuntimeError("boom")
        mocker.patch(
            "src.modules.azure_backup_hana.ManagedIdentityCredential",
        )
        mocker.patch(
            "src.modules.azure_backup_hana.RecoveryServicesBackupClient",
            return_value=mock_client,
        )

        run_module()

        assert fail_kwargs.get("status") == TestStatus.ERROR.value
