# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Workspace discovery and classification.

After setup.sh runs on a deployer VM, this module discovers which
workspaces exist and determines which test groups apply to each,
based on the sap-parameters.yaml flags (database_high_availability,
scs_high_availability).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from e2e.src.config import E2EConfig, TestGroup
from e2e.src.remote_executor import RemoteExecutor

logger = logging.getLogger(__name__)

_REPO_DIR = "/root/sap-automation-qa"


@dataclass
class WorkspaceCapability:
    """What a discovered workspace supports.

    :param workspace_id: Directory name under WORKSPACES/SYSTEM.
    :param sap_sid: SAP System ID extracted from sap-parameters.
    :param has_hosts_yaml: Whether hosts.yaml exists.
    :param has_sap_params: Whether sap-parameters.yaml exists.
    :param database_ha: database_high_availability flag.
    :param scs_ha: scs_high_availability flag.
    :param platform: Database platform (HANA, etc.).
    :param cluster_type: Cluster fencing type (AFA, ISCSI, ASD).
    :param nfs_provider: NFS provider (AFS, ANF).
    :param has_ssh_key: Whether an SSH key file exists.
    :param has_password: Whether a password file exists.
    :param applicable_groups: Test groups this workspace can run.
    """

    workspace_id: str = ""
    sap_sid: str = ""
    has_hosts_yaml: bool = False
    has_sap_params: bool = False
    database_ha: bool = False
    database_scale_out: bool = False
    scs_ha: bool = False
    platform: str = ""
    cluster_type: str = ""
    nfs_provider: str = ""
    has_ssh_key: bool = False
    has_password: bool = False
    applicable_groups: list[str] = field(default_factory=list)


def _classify_workspace(ws: WorkspaceCapability) -> None:
    """Populate ``applicable_groups`` based on capability flags.

    :param ws: Workspace to classify in-place.
    """
    groups: list[str] = []

    if ws.has_hosts_yaml and ws.has_sap_params:
        groups.append(TestGroup.CONFIGURATION_CHECKS.value)

    if ws.database_ha and ws.has_hosts_yaml:
        groups.append(TestGroup.DATABASE_HA.value)

    if ws.scs_ha and ws.has_hosts_yaml:
        groups.append(TestGroup.CENTRAL_SERVICES_HA.value)

    ws.applicable_groups = groups


def discover_workspaces(
    executor: RemoteExecutor,
    config: E2EConfig,
    repo_dir: str = _REPO_DIR,
) -> list[WorkspaceCapability]:
    """Discover and classify workspaces on a remote deployer VM.

    Runs a small Python snippet over SSH that introspects every
    directory under ``WORKSPACES/SYSTEM/``, reads sap-parameters.yaml,
    and returns structured JSON.

    :param executor: SSH executor connected to the VM.
    :param config: E2E configuration (for workspace filters).
    :param repo_dir: Path to the cloned repo on the VM.
    :returns: Classified workspace list.
    :rtype: list[WorkspaceCapability]
    """
    discover_script = r"""
import json, os, sys
try:
    import yaml
except ImportError:
    yaml = None

base = sys.argv[1]
results = []
if not os.path.isdir(base):
    print(json.dumps(results))
    sys.exit(0)

for name in sorted(os.listdir(base)):
    ws_dir = os.path.join(base, name)
    if not os.path.isdir(ws_dir) or name.startswith('.'):
        continue

    hosts_yaml = os.path.join(ws_dir, 'hosts.yaml')
    sap_params = os.path.join(ws_dir, 'sap-parameters.yaml')
    has_hosts = os.path.isfile(hosts_yaml)
    has_params = os.path.isfile(sap_params)

    if not has_hosts and not has_params:
        continue

    entry = {
        'workspace_id': name,
        'has_hosts_yaml': has_hosts,
        'has_sap_params': has_params,
        'sap_sid': '',
        'database_ha': False,
        'database_scale_out': False,
        'scs_ha': False,
        'platform': '',
        'cluster_type': '',
        'nfs_provider': '',
        'has_ssh_key': False,
        'has_password': False,
    }

    if has_params and yaml:
        try:
            with open(sap_params) as f:
                p = yaml.safe_load(f) or {}
            entry['sap_sid'] = p.get('sap_sid', '')
            entry['database_ha'] = bool(
                p.get('database_high_availability', False)
            )
            entry['database_scale_out'] = bool(
                p.get('database_scale_out', False)
                or p.get(
                    'database_HANA_use_scaleout_scenario',
                    False,
                )
            )
            entry['scs_ha'] = bool(
                p.get('scs_high_availability', False)
            )
            entry['platform'] = p.get('platform', '')
            entry['cluster_type'] = (
                p.get('database_cluster_type', '')
                or p.get('scs_cluster_type', '')
            )
            entry['nfs_provider'] = p.get('NFS_provider', '')
        except Exception:
            pass

    ssh_exts = ['ppk','pem','key','private','rsa','ed25519','']
    for ext in ssh_exts:
        fname = f'ssh_key.{ext}' if ext else 'ssh_key'
        if os.path.isfile(os.path.join(ws_dir, fname)):
            entry['has_ssh_key'] = True
            break

    entry['has_password'] = os.path.isfile(
        os.path.join(ws_dir, 'password')
    )

    results.append(entry)

print(json.dumps(results))
"""

    ws_base = f"{repo_dir}/WORKSPACES/SYSTEM"

    result = executor.run(
        f"python3 -c {_shell_quote(discover_script)} {ws_base}",
        timeout=60,
    )

    if result.return_code != 0:
        logger.error("Workspace discovery failed: %s", result.stderr)
        return []

    try:
        raw_list = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        logger.error(
            "Invalid JSON from workspace discovery: %s",
            result.stdout[:200],
        )
        return []

    workspaces: list[WorkspaceCapability] = []
    for entry in raw_list:
        ws = WorkspaceCapability(**entry)
        _classify_workspace(ws)

        if config.workspace_configs and (ws.workspace_id not in config.workspace_configs):
            logger.debug(
                "Skipping workspace %s (not in filter)",
                ws.workspace_id,
            )
            continue

        if not ws.applicable_groups:
            logger.debug(
                "Skipping workspace %s (no applicable tests)",
                ws.workspace_id,
            )
            continue

        workspaces.append(ws)

    logger.info(
        "Discovered %d testable workspace(s): %s",
        len(workspaces),
        [w.workspace_id for w in workspaces],
    )
    return workspaces


def _shell_quote(s: str) -> str:
    """Single-quote a string for bash, escaping inner quotes.

    :param s: Input string.
    :returns: Shell-safe quoted string.
    :rtype: str
    """
    return "'" + s.replace("'", "'\"'\"'") + "'"
