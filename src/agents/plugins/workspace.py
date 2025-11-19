# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Semantic Kernel plugin for SAP QA workspace management.

This plugin provides workspace-related functions that can be called
by Semantic Kernel agents using function calling.
"""

import json
import logging
import yaml
from pathlib import Path
from typing import Annotated, Optional

from semantic_kernel.functions import kernel_function

from src.agents.workspace.workspace_store import WorkspaceStore
from src.agents.logging_config import get_logger

logger = get_logger(__name__)


class WorkspacePlugin:
    """Semantic Kernel plugin for managing SAP QA workspaces.

    This plugin exposes workspace operations as SK functions that
    the LLM can call during agent execution.
    """

    def __init__(self, store: WorkspaceStore) -> None:
        """Initialize workspace plugin.

        :param store: WorkspaceStore instance for managing workspaces
        :type store: WorkspaceStore
        """
        self.store = store
        logger.info(f"WorkspacePlugin initialized with store root: {store.root_path}")

    @kernel_function(
        name="list_workspaces",
        description="List all existing SAP QA system workspaces. Returns workspace IDs in"
        + f" format ENV-REGION-DEPLOYMENT-SID.",
    )
    def list_workspaces(self) -> Annotated[str, "JSON string with list of workspace IDs"]:
        """List all workspace IDs.

        :returns: JSON string with workspace_ids array
        :rtype: str

        Example output:
            {"workspaces": ["DEV-WEEU-SAP01-X00", "QA-WEEU-SAP01-X01"]}
        """
        logger.info("list_workspaces called")

        workspaces = self.store.list_workspaces()
        workspace_ids = [ws.workspace_id for ws in workspaces]

        result = {"workspaces": workspace_ids}
        logger.info(f"Found {len(workspace_ids)} workspaces")

        return json.dumps(result)

    @kernel_function(
        name="find_workspace_by_sid_env",
        description="Find SAP QA workspaces matching a specific System ID (SID) and optionally an"
        + f" environment. If env is not provided or empty, returns ALL workspaces with that "
        + f"SID across all environments.",
    )
    def find_workspace_by_sid_env(
        self,
        sid: Annotated[str, "SAP System ID (3 characters, e.g., X00, P01, HDB)"],
        env: Annotated[
            str,
            "Environment name (e.g., DEV, QA, PROD). Leave empty to search across all environments.",
        ] = "",
    ) -> Annotated[str, "JSON string with matching workspace metadata"]:
        """Find workspaces matching SID and optionally environment.

        :param sid: SAP System ID
        :type sid: str
        :param env: Environment (DEV, QA, PROD) or empty string to search all
        :type env: str
        :returns: JSON string with matching workspace metadata
        :rtype: str

        Example output:
            {
                "matches": [
                    {
                        "workspace_id": "DEV-WEEU-SAP01-X00",
                        "env": "DEV",
                        "region": "WEEU",
                        "deployment_code": "SAP01",
                        "sid": "X00",
                        "path": "/path/to/workspace"
                    }
                ],
                "count": 1
            }
        """
        logger.info(f"find_workspace_by_sid_env called with sid={sid}, env={env or 'ALL'}")
        if not env or env.strip() == "":
            matches = self.store.find_by_sid_env(sid=sid, env=None)
        else:
            matches = self.store.find_by_sid_env(sid=sid, env=env)

        result = {"matches": [ws.to_dict() for ws in matches], "count": len(matches)}
        logger.info(f"Found {len(matches)} matching workspaces")

        return json.dumps(result)

    @kernel_function(
        name="get_workspace",
        description="Get full metadata for a specific SAP QA workspace by its ID. Returns "
        + f"workspace details including path, environment, region, deployment code, and SID.",
    )
    def get_workspace(
        self,
        workspace_id: Annotated[
            str,
            "Full workspace identifier in format ENV-REGION-DEPLOYMENT-SID (e.g., DEV-WEEU-SAP01-X00)",
        ],
    ) -> Annotated[str, "JSON string with workspace metadata or error"]:
        """Get workspace metadata by ID.

        :param workspace_id: Workspace identifier
        :type workspace_id: str
        :returns: JSON string with workspace metadata or error
        :rtype: str

        Example output (success):
            {
                "workspace_id": "DEV-WEEU-SAP01-X00",
                "env": "DEV",
                "region": "WEEU",
                "deployment_code": "SAP01",
                "sid": "X00",
                "path": "/path/to/workspace"
            }

        Example output (not found):
            {"error": "Workspace not found", "workspace_id": "..."}
        """
        logger.info(f"get_workspace called with workspace_id={workspace_id}")

        workspace = self.store.get_workspace(workspace_id)

        if workspace is None:
            result = {"error": "Workspace not found", "workspace_id": workspace_id}
            logger.warning(f"Workspace {workspace_id} not found")
        else:
            result = workspace.to_dict()
            logger.info(f"Retrieved workspace {workspace_id}")

        return json.dumps(result)

    @kernel_function(
        name="create_workspace",
        description="Create a new SAP QA workspace directory. The workspace ID is automatically "
        + f"generated from the provided parameters in format ENV-REGION-DEPLOYMENT-SID. If "
        + f"workspace already exists, returns existing metadata.",
    )
    def create_workspace(
        self,
        env: Annotated[str, "Environment name (e.g., DEV, QA, PROD)"],
        region: Annotated[str, "Azure region code (e.g., WEEU for West Europe, EAUS for East US)"],
        deployment_code: Annotated[str, "Deployment identifier (e.g., SAP01, SAP02)"],
        sid: Annotated[str, "SAP System ID (3 characters, e.g., X00, P01)"],
    ) -> Annotated[str, "JSON string with workspace metadata and creation status"]:
        """Create a new workspace.

        :param env: Environment name
        :type env: str
        :param region: Azure region code
        :type region: str
        :param deployment_code: Deployment identifier
        :type deployment_code: str
        :param sid: SAP System ID
        :type sid: str
        :returns: JSON string with workspace metadata and creation flags
        :rtype: str

        Example output (newly created):
            {
                "workspace_id": "DEV-WEEU-SAP01-X00",
                "env": "DEV",
                "region": "WEEU",
                "deployment_code": "SAP01",
                "sid": "X00",
                "path": "/path/to/workspace",
                "created": true,
                "exists": false
            }

        Example output (already exists):
            {
                "workspace_id": "DEV-WEEU-SAP01-X00",
                ...,
                "created": false,
                "exists": true
            }
        """
        logger.info(
            f"create_workspace called with env={env}, region={region}, "
            + f"deployment_code={deployment_code}, sid={sid}"
        )

        workspace, is_new = self.store.create_workspace(
            env=env, region=region, deployment_code=deployment_code, sid=sid
        )

        result = workspace.to_dict()
        result["created"] = is_new
        result["exists"] = not is_new

        if is_new:
            logger.info(f"Created new workspace {workspace.workspace_id}")
        else:
            logger.info(f"Workspace {workspace.workspace_id} already exists")

        return json.dumps(result)

    def _load_sap_parameters_dict(self, workspace_id: str) -> Optional[dict]:
        """Load sap-parameters.yaml for a workspace.

        :param workspace_id: Workspace identifier
        :type workspace_id: str
        :returns: Dictionary with SAP parameters or None if file doesn't exist
        :rtype: Optional[dict]
        """
        workspace_path = self.store.root_path / workspace_id
        sap_params_file = workspace_path / "sap-parameters.yaml"

        if not sap_params_file.exists():
            logger.warning(f"sap-parameters.yaml not found for workspace {workspace_id}")
            return None

        try:
            with open(sap_params_file, "r") as f:
                params = yaml.safe_load(f)
            logger.info(f"Loaded sap-parameters.yaml for workspace {workspace_id}")
            return params
        except Exception as e:
            logger.error(f"Error loading sap-parameters.yaml for {workspace_id}: {e}")
            return None

    @kernel_function(
        name="get_sap_parameters_for_workspace",
        description="Get SAP system parameters from sap-parameters.yaml for a workspace. "
        + f"Returns actual SAP configuration including HA settings, cluster types, SIDs, etc.",
    )
    def get_sap_parameters_for_workspace(
        self, workspace_id: Annotated[str, "Workspace ID in format ENV-REGION-DEPLOYMENT-SID"]
    ) -> Annotated[str, "JSON string with SAP parameters or error"]:
        """Get SAP parameters for a workspace.

        :param workspace_id: Workspace identifier
        :type workspace_id: str
        :returns: JSON string with parameters or error message
        :rtype: str
        """
        logger.info(f"get_sap_parameters_for_workspace called for {workspace_id}")

        params = self._load_sap_parameters_dict(workspace_id)

        if params is None:
            return json.dumps(
                {"error": "sap-parameters.yaml not found", "workspace_id": workspace_id}
            )

        return json.dumps({"workspace_id": workspace_id, "parameters": params})

    def _derive_capabilities_from_sap_parameters(self, params: dict, workspace_id: str) -> dict:
        """Derive system capabilities from sap-parameters.yaml.

        This function ONLY reads from the parameters dict and does NOT infer
        anything from SID or workspace name.

        :param params: SAP parameters dictionary
        :type params: dict
        :param workspace_id: Workspace ID (used only for env extraction)
        :type workspace_id: str
        :returns: Dictionary with normalized capability flags
        :rtype: dict
        """
        capabilities = {}
        env = workspace_id.split("-")[0] if "-" in workspace_id else "UNKNOWN"
        capabilities["system_role"] = env
        platform = params.get("platform", "").upper()
        capabilities["hana"] = platform == "HANA"
        capabilities["database_platform"] = platform if platform else "NONE"
        db_ha = params.get("database_high_availability", False)
        capabilities["database_high_availability"] = bool(db_ha)
        capabilities["database_cluster_type"] = params.get("database_cluster_type", "NONE")
        scs_ha = params.get("scs_high_availability", False)
        capabilities["scs_high_availability"] = bool(scs_ha)
        capabilities["scs_cluster_type"] = params.get("scs_cluster_type", "NONE")
        capabilities["ascs_ers"] = bool(scs_ha)
        capabilities["ha_cluster"] = db_ha or scs_ha

        capabilities["nfs_provider"] = params.get("NFS_provider", "NONE")
        capabilities["sap_sid"] = params.get("sap_sid", "UNKNOWN")
        capabilities["db_sid"] = params.get("db_sid", "UNKNOWN")
        capabilities["db_instance_number"] = params.get("db_instance_number", "UNKNOWN")
        capabilities["scs_instance_number"] = params.get("scs_instance_number", "UNKNOWN")
        capabilities["ers_instance_number"] = params.get("ers_instance_number", "UNKNOWN")

        logger.info(f"Derived capabilities for {workspace_id}: {capabilities}")
        return capabilities

    @kernel_function(
        name="get_system_capabilities_for_workspace",
        description="Get derived system capabilities based on actual SAP configuration. Returns "
        + f"normalized flags for HANA, HA cluster, ASCS/ERS, etc. NEVER infers from SID.",
    )
    def get_system_capabilities_for_workspace(
        self, workspace_id: Annotated[str, "Workspace ID in format ENV-REGION-DEPLOYMENT-SID"]
    ) -> Annotated[str, "JSON string with system capabilities or error"]:
        """Get system capabilities derived from SAP parameters.

        :param workspace_id: Workspace identifier
        :type workspace_id: str
        :returns: JSON string with capabilities or error message
        :rtype: str
        """
        logger.info(f"get_system_capabilities_for_workspace called for {workspace_id}")

        params = self._load_sap_parameters_dict(workspace_id)

        if params is None:
            return json.dumps(
                {
                    "error": f"sap-parameters.yaml not found for workspace {workspace_id}",
                    "workspace_id": workspace_id,
                }
            )

        capabilities = self._derive_capabilities_from_sap_parameters(params, workspace_id)

        return json.dumps({"workspace_id": workspace_id, "capabilities": capabilities})
