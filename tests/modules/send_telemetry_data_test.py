# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Unit tests for the send_telemetry_data module.
"""

import base64
import json
import pytest
from src.modules.send_telemetry_data import TelemetryDataSender, main


class TestTelemetryDataSender:
    """
    Test cases for the TelemetryDataSender class.
    """

    @pytest.fixture
    def module_params(self):
        """
        Fixture for providing sample module parameters.

        :return: Sample module parameters.
        :rtype: dict
        """
        return {
            "test_group_json_data": {"TestGroupInvocationId": "12345"},
            "telemetry_data_destination": "azureloganalytics",
            "laws_workspace_id": "workspace_id",
            "laws_shared_key": base64.b64encode(b"shared_key").decode("utf-8"),
            "telemetry_table_name": "telemetry_table",
            "adx_database_name": "adx_database",
            "adx_cluster_fqdn": "adx_cluster",
            "adx_client_id": "adx_client",
            "workspace_directory": "/tmp",
        }

    @pytest.fixture
    def module_params_adx(self):
        """
        Fixture for providing sample module parameters.

        :return: Sample module parameters.
        :rtype: dict
        """
        return {
            "test_group_json_data": {"TestGroupInvocationId": "12345"},
            "telemetry_data_destination": "azuredataexplorer",
            "laws_workspace_id": "workspace_id",
            "laws_shared_key": base64.b64encode(b"shared_key").decode("utf-8"),
            "telemetry_table_name": "telemetry_table",
            "adx_database_name": "adx_database",
            "adx_cluster_fqdn": "adx_cluster",
            "adx_client_id": "adx_client",
            "workspace_directory": "/tmp",
        }

    @pytest.fixture
    def module_params_list(self):
        """
        Fixture providing a list payload for batched telemetry.

        :return: Sample module parameters with list payload.
        :rtype: dict
        """
        return {
            "test_group_json_data": [
                {
                    "TestGroupInvocationId": "12345",
                    "TestCaseInvocationId": "c1",
                    "TestCaseName": "check1",
                },
                {
                    "TestGroupInvocationId": "12345",
                    "TestCaseInvocationId": "c2",
                    "TestCaseName": "check2",
                },
            ],
            "telemetry_data_destination": "azureloganalytics",
            "laws_workspace_id": "workspace_id",
            "laws_shared_key": base64.b64encode(b"shared_key").decode("utf-8"),
            "telemetry_table_name": "telemetry_table",
            "adx_database_name": "adx_database",
            "adx_cluster_fqdn": "adx_cluster",
            "adx_client_id": "adx_client",
            "workspace_directory": "/tmp",
        }

    @pytest.fixture
    def telemetry_data_sender(self, module_params):
        """
        Fixture for creating a TelemetryDataSender instance.

        :param module_params: Sample module parameters.
        :type module_params: dict
        :return: TelemetryDataSender instance.
        :rtype: TelemetryDataSender
        """
        return TelemetryDataSender(module_params)

    @pytest.fixture
    def telemetry_data_sender_adx(self, module_params_adx):
        """
        Fixture for creating a TelemetryDataSender instance.

        :param module_params_adx: Sample module parameters.
        :type module_params_adx: dict
        :return: TelemetryDataSender instance.
        :rtype: TelemetryDataSender
        """
        return TelemetryDataSender(module_params_adx)

    def test_send_telemetry_data_to_azuredataexplorer(self, mocker, telemetry_data_sender):
        """
        Test the send_telemetry_data_to_azuredataexplorer method.

        :param mocker: Mocker fixture for mocking functions.
        :type mocker: _azure.kusto.ingest.QueuedIngestClient
        :param telemetry_data_sender: TelemetryDataSender instance.
        :type telemetry_data_sender: TelemetryDataSender
        """
        mock_kusto = mocker.patch("azure.kusto.ingest.QueuedIngestClient.ingest_from_dataframe")
        mock_kusto.return_value = "response"

        response = telemetry_data_sender.send_telemetry_data_to_azuredataexplorer(
            telemetry_json_data=json.dumps({"key": "value"})
        )
        assert response == "response"

    def test_send_telemetry_data_to_azureloganalytics(self, mocker, telemetry_data_sender):
        """
        Test the send_telemetry_data_to_azureloganalytics method.

        :param mocker: Mocker fixture for mocking functions.
        :type mocker: _azure.kusto.ingest.QueuedIngestClient
        :param telemetry_data_sender: TelemetryDataSender instance.
        :type telemetry_data_sender: TelemetryDataSender
        """
        mock_requests = mocker.patch("requests.post")
        mock_requests.return_value.status_code = 200

        response = telemetry_data_sender.send_telemetry_data_to_azureloganalytics(
            telemetry_json_data=json.dumps({"key": "value"})
        )
        assert response.status_code == 200

    def test_validate_params(self, telemetry_data_sender):
        """
        Test the validate_params method.

        :param telemetry_data_sender: TelemetryDataSender instance.
        :type telemetry_data_sender: TelemetryDataSender
        """
        assert telemetry_data_sender.validate_params() is True

    def test_validate_params_adx(self, telemetry_data_sender_adx):
        """
        Test the validate_params method for ADX.

        :param telemetry_data_sender_adx: TelemetryDataSender instance.
        :type telemetry_data_sender_adx: TelemetryDataSender
        """
        assert telemetry_data_sender_adx.validate_params() is True

    def test_write_log_file(self, mocker, telemetry_data_sender):
        """
        Test the write_log_file method.

        :param mocker: Mocker fixture for mocking functions.
        :type mocker: pytest_mock.MockerFixture
        :param telemetry_data_sender: TelemetryDataSender instance.
        :type telemetry_data_sender: TelemetryDataSender
        """
        mock_open = mocker.patch("builtins.open", mocker.mock_open())
        telemetry_data_sender.write_log_file()
        mock_open.assert_called_once_with("/tmp/logs/12345.log", "a", encoding="utf-8")

    def test_write_log_file_with_list_payload(self, mocker, module_params_list):
        """
        Ensure write_log_file handles list payloads and uses the first element's TestGroupInvocationId.
        """
        sender = TelemetryDataSender(module_params_list)
        mock_open = mocker.patch("builtins.open", mocker.mock_open())
        mocker.patch("os.makedirs")
        sender.write_log_file()
        mock_open.assert_called_once_with("/tmp/logs/12345.log", "a", encoding="utf-8")

    def test_validate_params_accepts_list_payload(self, module_params_list):
        """
        validate_params should return True for list payloads when required params exist.
        """
        sender = TelemetryDataSender(module_params_list)
        assert sender.validate_params() is True

    def test_send_telemetry_data_with_list_calls_laws(self, mocker, module_params_list):
        """
        When provided a list payload and LAWS destination, ensure the module calls requests.post.
        """
        sender = TelemetryDataSender(module_params_list)
        mock_validate = mocker.patch.object(sender, "validate_params")
        mock_validate.return_value = True
        mock_post = mocker.patch("requests.post")
        mock_post.return_value.status_code = 200

        sender.send_telemetry_data()
        assert mock_post.call_count == 1

    def test_fetch_laws_shared_key_success(self, mocker, telemetry_data_sender):
        """
        Test successful shared key retrieval using Azure SDK per Microsoft documentation.
        """
        telemetry_data_sender.module_params["laws_subscription_id"] = "sub123"
        telemetry_data_sender.module_params["laws_resource_group"] = "rg-test"
        telemetry_data_sender.module_params["laws_workspace_name"] = "ws-test"

        mock_credential = mocker.patch("src.modules.send_telemetry_data.DefaultAzureCredential")
        mock_credential.return_value = mocker.Mock()
        mock_client_class = mocker.patch(
            "src.modules.send_telemetry_data.LogAnalyticsManagementClient"
        )
        mock_client = mocker.Mock()
        mock_client_class.return_value = mock_client

        mock_response = mocker.Mock()
        mock_response.primary_shared_key = "fetched_key_abc"
        mock_client.shared_keys.get_shared_keys.return_value = mock_response

        key = telemetry_data_sender._fetch_laws_shared_key()
        assert key == "fetched_key_abc"
        mock_client.shared_keys.get_shared_keys.assert_called_once_with(
            resource_group_name="rg-test", workspace_name="ws-test"
        )

    def test_fetch_laws_shared_key_missing_subscription_id(self, mocker, telemetry_data_sender):
        """
        Test that missing subscription_id raises ValueError.
        """
        telemetry_data_sender.module_params["laws_resource_group"] = "rg-test"
        telemetry_data_sender.module_params["laws_workspace_name"] = "ws-test"

        with pytest.raises(ValueError, match="laws_subscription_id"):
            telemetry_data_sender._fetch_laws_shared_key()

    def test_fetch_laws_shared_key_missing_resource_group(self, mocker, telemetry_data_sender):
        """
        Test that missing resource_group raises ValueError.
        """
        telemetry_data_sender.module_params["laws_subscription_id"] = "sub123"
        telemetry_data_sender.module_params["laws_workspace_name"] = "ws-test"

        with pytest.raises(ValueError, match="laws_resource_group"):
            telemetry_data_sender._fetch_laws_shared_key()

    def test_fetch_laws_shared_key_missing_workspace_name(self, mocker, telemetry_data_sender):
        """
        Test that missing workspace_name raises ValueError.
        """
        telemetry_data_sender.module_params["laws_subscription_id"] = "sub123"
        telemetry_data_sender.module_params["laws_resource_group"] = "rg-test"

        with pytest.raises(ValueError, match="laws_workspace_name"):
            telemetry_data_sender._fetch_laws_shared_key()

    def test_fetch_laws_shared_key_credential_failure(self, mocker, telemetry_data_sender):
        """
        Test that DefaultAzureCredential failure is handled properly.
        """
        telemetry_data_sender.module_params["laws_subscription_id"] = "sub123"
        telemetry_data_sender.module_params["laws_resource_group"] = "rg-test"
        telemetry_data_sender.module_params["laws_workspace_name"] = "ws-test"

        mock_credential = mocker.patch("src.modules.send_telemetry_data.DefaultAzureCredential")
        mock_credential.side_effect = Exception("Credential acquisition failed")

        with pytest.raises(Exception, match="Credential acquisition failed"):
            telemetry_data_sender._fetch_laws_shared_key()

    def test_fetch_laws_shared_key_api_call_failure(self, mocker, telemetry_data_sender):
        """
        Test that API call failure is handled properly.
        """
        telemetry_data_sender.module_params["laws_subscription_id"] = "sub123"
        telemetry_data_sender.module_params["laws_resource_group"] = "rg-test"
        telemetry_data_sender.module_params["laws_workspace_name"] = "ws-test"

        mock_credential = mocker.patch("src.modules.send_telemetry_data.DefaultAzureCredential")
        mock_credential.return_value = mocker.Mock()

        mock_client_class = mocker.patch(
            "src.modules.send_telemetry_data.LogAnalyticsManagementClient"
        )
        mock_client = mocker.Mock()
        mock_client_class.return_value = mock_client
        mock_client.shared_keys.get_shared_keys.side_effect = Exception("API call failed")

        with pytest.raises(Exception, match="API call failed"):
            telemetry_data_sender._fetch_laws_shared_key()

    def test_fetch_laws_shared_key_no_primary_key_in_response(self, mocker, telemetry_data_sender):
        """
        Test that missing primary_shared_key in response raises ValueError.
        """
        telemetry_data_sender.module_params["laws_subscription_id"] = "sub123"
        telemetry_data_sender.module_params["laws_resource_group"] = "rg-test"
        telemetry_data_sender.module_params["laws_workspace_name"] = "ws-test"

        mock_credential = mocker.patch("src.modules.send_telemetry_data.DefaultAzureCredential")
        mock_credential.return_value = mocker.Mock()

        mock_client_class = mocker.patch(
            "src.modules.send_telemetry_data.LogAnalyticsManagementClient"
        )
        mock_client = mocker.Mock()
        mock_client_class.return_value = mock_client
        mock_response = mocker.Mock()
        mock_response.primary_shared_key = None
        mock_client.shared_keys.get_shared_keys.return_value = mock_response

        with pytest.raises(ValueError, match="Primary shared key not found"):
            telemetry_data_sender._fetch_laws_shared_key()

    def test_fetch_laws_shared_key_empty_key_in_response(self, mocker, telemetry_data_sender):
        """
        Test that empty primary_shared_key in response raises ValueError.
        """
        telemetry_data_sender.module_params["laws_subscription_id"] = "sub123"
        telemetry_data_sender.module_params["laws_resource_group"] = "rg-test"
        telemetry_data_sender.module_params["laws_workspace_name"] = "ws-test"

        mock_credential = mocker.patch("src.modules.send_telemetry_data.DefaultAzureCredential")
        mock_credential.return_value = mocker.Mock()

        mock_client_class = mocker.patch(
            "src.modules.send_telemetry_data.LogAnalyticsManagementClient"
        )
        mock_client = mocker.Mock()
        mock_client_class.return_value = mock_client
        mock_response = mocker.Mock()
        mock_response.primary_shared_key = ""
        mock_client.shared_keys.get_shared_keys.return_value = mock_response

        with pytest.raises(ValueError, match="Primary shared key not found"):
            telemetry_data_sender._fetch_laws_shared_key()

    def test_fetch_laws_shared_key_with_user_assigned_identity(self, mocker, telemetry_data_sender):
        """
        Test that user-assigned managed identity is used when client_id is provided.
        """
        telemetry_data_sender.module_params["laws_subscription_id"] = "sub123"
        telemetry_data_sender.module_params["laws_resource_group"] = "rg-test"
        telemetry_data_sender.module_params["laws_workspace_name"] = "ws-test"
        telemetry_data_sender.module_params["user_assigned_identity_client_id"] = (
            "user-mi-client-id"
        )

        mock_mi_credential = mocker.patch(
            "src.modules.send_telemetry_data.ManagedIdentityCredential"
        )
        mock_mi_credential.return_value = mocker.Mock()
        mock_client_class = mocker.patch(
            "src.modules.send_telemetry_data.LogAnalyticsManagementClient"
        )
        mock_client = mocker.Mock()
        mock_client_class.return_value = mock_client

        mock_response = mocker.Mock()
        mock_response.primary_shared_key = "fetched_key_with_user_mi"
        mock_client.shared_keys.get_shared_keys.return_value = mock_response

        key = telemetry_data_sender._fetch_laws_shared_key()
        mock_mi_credential.assert_called_once_with(client_id="user-mi-client-id")
        assert key == "fetched_key_with_user_mi"

    def test_fetch_laws_shared_key_empty_user_assigned_identity_uses_default(
        self, mocker, telemetry_data_sender
    ):
        """
        Test that DefaultAzureCredential is used when user_assigned_identity_client_id is empty string.
        """
        telemetry_data_sender.module_params["laws_subscription_id"] = "sub123"
        telemetry_data_sender.module_params["laws_resource_group"] = "rg-test"
        telemetry_data_sender.module_params["laws_workspace_name"] = "ws-test"
        telemetry_data_sender.module_params["user_assigned_identity_client_id"] = ""
        mock_default_credential = mocker.patch(
            "src.modules.send_telemetry_data.DefaultAzureCredential"
        )
        mock_default_credential.return_value = mocker.Mock()
        mock_client_class = mocker.patch(
            "src.modules.send_telemetry_data.LogAnalyticsManagementClient"
        )
        mock_client = mocker.Mock()
        mock_client_class.return_value = mock_client

        mock_response = mocker.Mock()
        mock_response.primary_shared_key = "fetched_key_default"
        mock_client.shared_keys.get_shared_keys.return_value = mock_response

        key = telemetry_data_sender._fetch_laws_shared_key()
        mock_default_credential.assert_called_once()
        assert key == "fetched_key_default"

    def test_fetch_laws_shared_key_whitespace_user_assigned_identity_uses_default(
        self, mocker, telemetry_data_sender
    ):
        """
        Test that DefaultAzureCredential is used when user_assigned_identity_client_id is whitespace.
        """
        telemetry_data_sender.module_params["laws_subscription_id"] = "sub123"
        telemetry_data_sender.module_params["laws_resource_group"] = "rg-test"
        telemetry_data_sender.module_params["laws_workspace_name"] = "ws-test"
        telemetry_data_sender.module_params["user_assigned_identity_client_id"] = "   "
        mock_default_credential = mocker.patch(
            "src.modules.send_telemetry_data.DefaultAzureCredential"
        )
        mock_default_credential.return_value = mocker.Mock()
        mock_client_class = mocker.patch(
            "src.modules.send_telemetry_data.LogAnalyticsManagementClient"
        )
        mock_client = mocker.Mock()
        mock_client_class.return_value = mock_client

        mock_response = mocker.Mock()
        mock_response.primary_shared_key = "fetched_key_default"
        mock_client.shared_keys.get_shared_keys.return_value = mock_response

        key = telemetry_data_sender._fetch_laws_shared_key()
        mock_default_credential.assert_called_once()
        assert key == "fetched_key_default"

    def test_validate_params_auto_fetches_shared_key(self, mocker):
        """
        Test that validate_params auto-fetches shared key when not provided.
        """
        params = {
            "test_group_json_data": {"TestGroupInvocationId": "12345"},
            "telemetry_data_destination": "azureloganalytics",
            "laws_workspace_id": "workspace_id",
            "laws_subscription_id": "sub123",
            "laws_resource_group": "rg-test",
            "laws_workspace_name": "ws-test",
            "telemetry_table_name": "telemetry_table",
            "workspace_directory": "/tmp",
        }
        sender = TelemetryDataSender(params)

        mock_fetch = mocker.patch.object(sender, "_fetch_laws_shared_key")
        mock_fetch.return_value = "auto_fetched_key"

        result = sender.validate_params()
        assert result is True
        assert sender.module_params["laws_shared_key"] == "auto_fetched_key"
        mock_fetch.assert_called_once()

    def test_send_telemetry_data(self, mocker, telemetry_data_sender):
        """
        Test the send_telemetry_data method.

        :param mocker: Mocker fixture for mocking functions.
        :type mocker: pytest_mock.MockerFixture
        :param telemetry_data_sender: TelemetryDataSender instance.
        :type telemetry_data_sender: TelemetryDataSender
        """
        mock_validate_params = mocker.patch.object(telemetry_data_sender, "validate_params")
        mock_validate_params.return_value = True
        mock_send_telemetry_data_to_azureloganalytics = mocker.patch.object(
            telemetry_data_sender, "send_telemetry_data_to_azureloganalytics"
        )
        mock_send_telemetry_data_to_azureloganalytics.return_value = "response"

        telemetry_data_sender.send_telemetry_data()
        assert telemetry_data_sender.result["status"] == "PASSED"

    def test_get_result(self, telemetry_data_sender):
        """
        Test the get_result method.

        :param telemetry_data_sender: TelemetryDataSender instance.
        :type telemetry_data_sender: TelemetryDataSender
        """
        result = telemetry_data_sender.get_result()
        assert "start" in result
        assert "end" in result

    def test_main_method(self, monkeypatch):
        """
        Test the main function of the send_telemetry_data module.

        :param monkeypatch: Monkeypatch fixture for mocking.
        :type monkeypatch: pytest.MonkeyPatch
        """
        mock_result = {}

        class MockAnsibleModule:
            """
            Mock class to simulate AnsibleModule behavior.
            """

            def __init__(self, *args, **kwargs):
                self.params = {
                    "test_group_json_data": {"TestGroupInvocationId": "12345"},
                    "telemetry_data_destination": "azureloganalyticss",
                    "laws_workspace_id": "workspace_id",
                    "laws_shared_key": base64.b64encode(b"shared_key").decode("utf-8"),
                    "telemetry_table_name": "telemetry_table",
                    "adx_database_name": "adx_database",
                    "adx_cluster_fqdn": "adx_cluster",
                    "adx_client_id": "adx_client",
                    "workspace_directory": "/tmp",
                }

            def exit_json(self, **kwargs):
                mock_result.update(kwargs)

        mock_ansible_module = MockAnsibleModule(
            argument_spec={},
            supports_check_mode=False,
        )
        monkeypatch.setattr(
            "src.modules.send_telemetry_data.AnsibleModule",
            lambda *args, **kwargs: mock_ansible_module,
        )

        main()

        assert mock_result["status"] == "PASSED"
