# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Semantic Kernel plugin for Azure Key Vault integration.

This plugin provides secure access to secrets stored in Azure Key Vault,
primarily used for retrieving SSH keys for SAP VM connectivity.

The plugin supports multiple authentication methods:
- User-assigned Managed Identity (preferred for SDAF deployments)
- System-assigned Managed Identity (when running on Azure VMs)
- DefaultAzureCredential fallback (Azure CLI for local development)
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Annotated, Optional
from urllib.parse import urlparse

import yaml
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.keyvault.secrets import SecretClient
from semantic_kernel.functions import kernel_function

from src.agents.logging_config import get_logger

logger = get_logger(__name__)


class KeyVaultPlugin:
    """Semantic Kernel plugin for Azure Key Vault secret management.

    This plugin provides secure access to SSH keys and other secrets
    stored in Azure Key Vault. It is designed to work with the SDAF
    deployment pattern where SSH keys are stored in Key Vault.

    Authentication priority:
    1. User-assigned Managed Identity (if client_id provided)
    2. System-assigned Managed Identity (on Azure VMs)
    3. DefaultAzureCredential (Azure CLI, environment variables, etc.)
    """

    def __init__(
        self,
        default_vault_name: Optional[str] = None,
        temp_key_dir: Optional[str] = None,
        managed_identity_client_id: Optional[str] = None,
    ) -> None:
        """Initialize KeyVaultPlugin.

        :param default_vault_name: Default Key Vault name (can be overridden per call)
        :type default_vault_name: Optional[str]
        :param temp_key_dir: Directory for temporary key files (defaults to system temp)
        :type temp_key_dir: Optional[str]
        :param managed_identity_client_id: Client ID for user-assigned managed identity
        :type managed_identity_client_id: Optional[str]
        """
        self.default_vault_name = default_vault_name or os.getenv("AZURE_KEYVAULT_NAME")
        self.temp_key_dir = Path(temp_key_dir) if temp_key_dir else Path(tempfile.gettempdir())
        self.default_managed_identity_client_id = managed_identity_client_id or os.getenv(
            "AZURE_CLIENT_ID"
        )
        self._credentials: dict = {}
        self._clients: dict = {}

        logger.info(
            f"KeyVaultPlugin initialized with default_vault: {self.default_vault_name}, "
            f"temp_key_dir: {self.temp_key_dir}, "
            f"default_managed_identity: {self.default_managed_identity_client_id or 'None (will use DefaultAzureCredential)'}"
        )

    def _get_credential(self, managed_identity_client_id: Optional[str] = None):
        """Get or create Azure credential.

        If managed_identity_client_id is provided, uses ManagedIdentityCredential
        with that specific user-assigned identity. Otherwise falls back to
        DefaultAzureCredential.

        :param managed_identity_client_id: Client ID for user-assigned managed identity
        :type managed_identity_client_id: Optional[str]
        :returns: Azure credential object
        :rtype: TokenCredential
        """
        client_id = managed_identity_client_id or self.default_managed_identity_client_id
        cache_key = client_id or "_default_"

        if cache_key not in self._credentials:
            if client_id and client_id != "00000000-0000-0000-0000-000000000000":
                self._credentials[cache_key] = ManagedIdentityCredential(
                    client_id=client_id
                )
                logger.info(
                    f"Azure credential initialized using ManagedIdentityCredential "
                    f"with client_id: {client_id}"
                )
            else:
                self._credentials[cache_key] = DefaultAzureCredential()
                logger.info("Azure credential initialized using DefaultAzureCredential")

        return self._credentials[cache_key]

    def _get_client(self, vault_name: str, managed_identity_client_id: Optional[str] = None):
        """Get or create SecretClient for a specific Key Vault.

        :param vault_name: Name of the Azure Key Vault
        :type vault_name: str
        :param managed_identity_client_id: Client ID for user-assigned managed identity
        :type managed_identity_client_id: Optional[str]
        :returns: SecretClient instance
        :rtype: SecretClient
        """
        client_id = managed_identity_client_id or self.default_managed_identity_client_id
        cache_key = (vault_name, client_id or "_default_")

        if cache_key not in self._clients:
            vault_url = f"https://{vault_name}.vault.azure.net"
            self._clients[cache_key] = SecretClient(
                vault_url=vault_url,
                credential=self._get_credential(client_id),
            )
            logger.info(
                f"SecretClient created for vault: {vault_name} "
                f"(identity: {client_id or 'default'})"
            )

        return self._clients[cache_key]

    @staticmethod
    def _parse_key_vault_id(key_vault_id: str) -> Optional[str]:
        """Extract Key Vault name from ARM resource ID.

        :param key_vault_id: Full ARM resource ID of the Key Vault
        :type key_vault_id: str
        :returns: Key Vault name or None if parsing fails
        :rtype: Optional[str]

        Example:
            Input: /subscriptions/.../Microsoft.KeyVault/vaults/my-vault
            Output: my-vault
        """
        if not key_vault_id:
            return None
        try:
            parts = key_vault_id.split("/")
            if "vaults" in parts:
                vault_idx = parts.index("vaults")
                if vault_idx + 1 < len(parts):
                    return parts[vault_idx + 1]
        except Exception as e:
            logger.warning(f"Failed to parse key_vault_id '{key_vault_id}': {e}")
        return None

    @staticmethod
    def _parse_secret_id(secret_id: str) -> tuple[Optional[str], Optional[str]]:
        """Extract vault name and secret name from Key Vault secret URL.

        :param secret_id: Full Key Vault secret URL
        :type secret_id: str
        :returns: Tuple of (vault_name, secret_name) or (None, None)
        :rtype: tuple[Optional[str], Optional[str]]

        Example:
            Input: https://my-vault.vault.azure.net/secrets/my-secret/version
            Output: ("my-vault", "my-secret")
        """
        if not secret_id:
            return None, None
        try:
            parsed = urlparse(secret_id)
            if parsed.netloc.endswith(".vault.azure.net"):
                vault_name = parsed.netloc.replace(".vault.azure.net", "")
                path_parts = parsed.path.strip("/").split("/")
                if len(path_parts) >= 2 and path_parts[0] == "secrets":
                    return vault_name, path_parts[1]
        except Exception as e:
            logger.warning(f"Failed to parse secret_id '{secret_id}': {e}")
        return None, None

    @kernel_function(
        name="get_secret",
        description="Retrieve a secret value from Azure Key Vault. Use this to fetch "
        + "credentials, connection strings, or other sensitive configuration values.",
    )
    def get_secret(
        self,
        secret_name: Annotated[str, "Name of the secret in Key Vault"],
        vault_name: Annotated[
            str,
            "Name of the Azure Key Vault (without .vault.azure.net). "
            "Leave empty to use default vault.",
        ] = "",
        managed_identity_client_id: Annotated[
            str,
            "Client ID of user-assigned managed identity. Leave empty to use default.",
        ] = "",
    ) -> Annotated[str, "JSON string with secret value or error"]:
        """Retrieve a secret from Azure Key Vault.

        :param secret_name: Name of the secret to retrieve
        :type secret_name: str
        :param vault_name: Key Vault name (uses default if empty)
        :type vault_name: str
        :param managed_identity_client_id: Client ID for user-assigned managed identity
        :type managed_identity_client_id: str
        :returns: JSON string with secret value or error message
        :rtype: str

        Example output (success):
            {"secret_name": "my-secret", "value": "secret-value", "vault": "my-vault"}

        Example output (error):
            {"error": "Secret not found", "secret_name": "my-secret"}
        """
        effective_vault = vault_name.strip() if vault_name else self.default_vault_name
        effective_identity = (
            managed_identity_client_id.strip()
            if managed_identity_client_id
            else None
        )

        if not effective_vault:
            error_msg = (
                "No Key Vault specified. Provide vault_name or set AZURE_KEYVAULT_NAME "
                "environment variable."
            )
            logger.error(error_msg)
            return json.dumps({"error": error_msg})

        identity_info = f" (identity: {effective_identity})" if effective_identity else ""
        logger.info(
            f"Retrieving secret '{secret_name}' from vault '{effective_vault}'{identity_info}"
        )

        try:
            client = self._get_client(effective_vault, effective_identity)
            secret = client.get_secret(secret_name)

            logger.info(f"Successfully retrieved secret '{secret_name}'")
            return json.dumps(
                {
                    "secret_name": secret_name,
                    "value": secret.value,
                    "vault": effective_vault,
                }
            )

        except Exception as e:
            error_msg = f"Failed to retrieve secret '{secret_name}': {str(e)}"
            logger.error(error_msg)
            return json.dumps(
                {
                    "error": error_msg,
                    "secret_name": secret_name,
                    "vault": effective_vault,
                }
            )

    @kernel_function(
        name="get_ssh_private_key",
        description="Retrieve SSH private key from Azure Key Vault and save it to a "
        + "temporary file with correct permissions (0600). Returns the path to the key file "
        + "which can be used with ansible_ssh_private_key_file.",
    )
    def get_ssh_private_key(
        self,
        secret_name: Annotated[
            str,
            "Name of the SSH key secret in Key Vault (e.g., 'sshkey', 'deployer-ssh-key')",
        ],
        vault_name: Annotated[
            str,
            "Name of the Azure Key Vault. Leave empty to use default vault.",
        ] = "",
        key_filename: Annotated[
            str,
            "Filename for the temporary key file (default: 'id_rsa')",
        ] = "id_rsa",
        managed_identity_client_id: Annotated[
            str,
            "Client ID of user-assigned managed identity. Leave empty to use default.",
        ] = "",
    ) -> Annotated[str, "JSON string with key file path or error"]:
        """Retrieve SSH private key and save to temporary file.

        This function:
        1. Fetches the SSH private key from Key Vault
        2. Saves it to a temporary file with restricted permissions (0600)
        3. Returns the path for use with Ansible

        :param secret_name: Name of the SSH key secret in Key Vault
        :type secret_name: str
        :param vault_name: Key Vault name (uses default if empty)
        :type vault_name: str
        :param key_filename: Filename for the temp key file
        :type key_filename: str
        :param managed_identity_client_id: Client ID for user-assigned managed identity
        :type managed_identity_client_id: str
        :returns: JSON string with key_path or error
        :rtype: str

        Example output (success):
            {
                "key_path": "/tmp/sap_keys/id_rsa",
                "secret_name": "sshkey",
                "vault": "my-vault",
                "permissions": "0600"
            }

        Example output (error):
            {"error": "Failed to retrieve SSH key", "secret_name": "sshkey"}
        """
        effective_vault = vault_name.strip() if vault_name else self.default_vault_name
        effective_identity = (
            managed_identity_client_id.strip()
            if managed_identity_client_id
            else None
        )

        if not effective_vault:
            error_msg = (
                "No Key Vault specified. Provide vault_name or set AZURE_KEYVAULT_NAME "
                "environment variable."
            )
            logger.error(error_msg)
            return json.dumps({"error": error_msg})

        identity_info = f" (identity: {effective_identity})" if effective_identity else ""
        logger.info(
            f"Retrieving SSH key '{secret_name}' from vault '{effective_vault}'{identity_info}"
        )

        try:
            client = self._get_client(effective_vault, effective_identity)
            secret = client.get_secret(secret_name)

            if not secret.value:
                error_msg = f"SSH key secret '{secret_name}' is empty"
                logger.error(error_msg)
                return json.dumps({"error": error_msg, "secret_name": secret_name})

            key_dir = self.temp_key_dir / "sap_keys"
            key_dir.mkdir(parents=True, exist_ok=True)

            key_path = key_dir / key_filename

            key_path.write_text(secret.value)

            key_path.chmod(0o600)

            logger.info(f"SSH key saved to '{key_path}' with permissions 0600")

            return json.dumps(
                {
                    "key_path": str(key_path),
                    "secret_name": secret_name,
                    "vault": effective_vault,
                    "permissions": "0600",
                }
            )

        except Exception as e:
            error_msg = f"Failed to retrieve SSH key '{secret_name}': {str(e)}"
            logger.error(error_msg)
            return json.dumps(
                {
                    "error": error_msg,
                    "secret_name": secret_name,
                    "vault": effective_vault,
                }
            )

    @kernel_function(
        name="get_ssh_key_for_workspace",
        description="Retrieve SSH private key for a specific SAP workspace. This function "
        + "reads the workspace's sap-parameters.yaml to determine the Key Vault name and "
        + "SSH key secret name, then fetches and saves the key.",
    )
    def get_ssh_key_for_workspace(
        self,
        workspace_id: Annotated[
            str,
            "Workspace ID in format ENV-REGION-DEPLOYMENT-SID (e.g., DEV-WEEU-SAP01-X00)",
        ],
        workspace_root: Annotated[
            str,
            "Root path to WORKSPACES/SYSTEM directory",
        ] = "WORKSPACES/SYSTEM",
    ) -> Annotated[str, "JSON string with key file path or error"]:
        """Retrieve SSH key for a workspace using its sap-parameters.yaml configuration.

        This function:
        1. Reads sap-parameters.yaml from the workspace
        2. Extracts Key Vault name, SSH key secret name, and managed identity client ID
        3. Fetches the key from Key Vault using the specified identity
        4. Saves it to a temporary file

        :param workspace_id: Workspace identifier
        :type workspace_id: str
        :param workspace_root: Path to WORKSPACES/SYSTEM directory
        :type workspace_root: str
        :returns: JSON string with key_path or error
        :rtype: str

        Example output (success):
            {
                "key_path": "/tmp/sap_keys/DEV-WEEU-SAP01-X00_id_rsa",
                "workspace_id": "DEV-WEEU-SAP01-X00",
                "vault": "DEVWEEUSAP01-vault",
                "secret_name": "sshkey",
                "identity": "12345678-1234-1234-1234-123456789abc"
            }
        """
        logger.info(f"Getting SSH key for workspace '{workspace_id}'")

        try:
            workspace_path = Path(workspace_root) / workspace_id
            params_path = workspace_path / "sap-parameters.yaml"

            if not params_path.exists():
                error_msg = f"sap-parameters.yaml not found at {params_path}"
                logger.error(error_msg)
                return json.dumps({"error": error_msg, "workspace_id": workspace_id})

            with open(params_path, "r") as f:
                params = yaml.safe_load(f)

            vault_name = params.get("kv_name") or params.get("keyvault_name")
            ssh_secret_name = params.get("sshkey_secret_name", "sshkey")
            managed_identity_client_id = params.get("user_assigned_identity_client_id")

            if not vault_name:
                vault_name = self.default_vault_name
                if not vault_name:
                    error_msg = (
                        f"Key Vault name not found in sap-parameters.yaml for workspace "
                        f"'{workspace_id}' and no default vault configured"
                    )
                    logger.error(error_msg)
                    return json.dumps({"error": error_msg, "workspace_id": workspace_id})

            identity_info = (
                f", identity: {managed_identity_client_id}"
                if managed_identity_client_id
                else ""
            )
            logger.info(
                f"Using vault '{vault_name}', secret '{ssh_secret_name}'{identity_info} "
                f"for workspace '{workspace_id}'"
            )

            key_filename = f"{workspace_id}_id_rsa"
            result = self.get_ssh_private_key(
                secret_name=ssh_secret_name,
                vault_name=vault_name,
                key_filename=key_filename,
                managed_identity_client_id=managed_identity_client_id or "",
            )

            result_dict = json.loads(result)
            result_dict["workspace_id"] = workspace_id
            if managed_identity_client_id:
                result_dict["identity"] = managed_identity_client_id

            return json.dumps(result_dict)

        except Exception as e:
            error_msg = f"Failed to get SSH key for workspace '{workspace_id}': {str(e)}"
            logger.error(error_msg)
            return json.dumps({"error": error_msg, "workspace_id": workspace_id})

    @kernel_function(
        name="list_secrets",
        description="List all secret names in an Azure Key Vault. Does not retrieve "
        + "secret values, only names. Useful for discovering available secrets.",
    )
    def list_secrets(
        self,
        vault_name: Annotated[
            str,
            "Name of the Azure Key Vault. Leave empty to use default vault.",
        ] = "",
        managed_identity_client_id: Annotated[
            str,
            "Client ID of user-assigned managed identity. Leave empty to use default.",
        ] = "",
    ) -> Annotated[str, "JSON string with list of secret names or error"]:
        """List all secret names in a Key Vault.

        :param vault_name: Key Vault name (uses default if empty)
        :type vault_name: str
        :param managed_identity_client_id: Client ID for user-assigned managed identity
        :type managed_identity_client_id: str
        :returns: JSON string with secret names or error
        :rtype: str

        Example output:
            {"vault": "my-vault", "secrets": ["sshkey", "db-password", "api-key"], "count": 3}
        """
        effective_vault = vault_name.strip() if vault_name else self.default_vault_name
        effective_identity = (
            managed_identity_client_id.strip()
            if managed_identity_client_id
            else None
        )

        if not effective_vault:
            error_msg = (
                "No Key Vault specified. Provide vault_name or set AZURE_KEYVAULT_NAME "
                "environment variable."
            )
            logger.error(error_msg)
            return json.dumps({"error": error_msg})

        identity_info = f" (identity: {effective_identity})" if effective_identity else ""
        logger.info(f"Listing secrets in vault '{effective_vault}'{identity_info}")

        try:
            client = self._get_client(effective_vault, effective_identity)
            secrets = list(client.list_properties_of_secrets())
            secret_names = [s.name for s in secrets]

            logger.info(f"Found {len(secret_names)} secrets in vault '{effective_vault}'")

            return json.dumps(
                {
                    "vault": effective_vault,
                    "secrets": secret_names,
                    "count": len(secret_names),
                }
            )

        except Exception as e:
            error_msg = f"Failed to list secrets in vault '{effective_vault}': {str(e)}"
            logger.error(error_msg)
            return json.dumps({"error": error_msg, "vault": effective_vault})

    def cleanup_temp_keys(self) -> None:
        """Clean up temporary SSH key files.

        This should be called when the plugin is no longer needed
        or at application shutdown to remove sensitive key files.
        """
        key_dir = self.temp_key_dir / "sap_keys"
        if key_dir.exists():
            for key_file in key_dir.glob("*"):
                try:
                    key_file.unlink()
                    logger.info(f"Removed temporary key file: {key_file}")
                except Exception as e:
                    logger.warning(f"Failed to remove key file {key_file}: {e}")

            try:
                key_dir.rmdir()
                logger.info(f"Removed temporary key directory: {key_dir}")
            except Exception as e:
                logger.warning(f"Failed to remove key directory {key_dir}: {e}")
