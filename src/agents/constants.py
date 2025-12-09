# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Constants for SAP QA Agent Framework.

This module centralizes all constants used across the agent plugins
to ensure consistency and maintainability.
"""

from typing import Set, Dict, Tuple

# =============================================================================
# Command Validation Constants
# =============================================================================

ALLOWED_BINARIES: Set[str] = {
    # File viewing
    "cat",
    "tail",
    "head",
    "grep",
    "egrep",
    "fgrep",
    "sed",
    "awk",
    "less",
    "more",
    # File system info
    "ls",
    "find",
    "df",
    "du",
    "stat",
    "file",
    "wc",
    # System info
    "free",
    "ps",
    "top",
    "uptime",
    "hostname",
    "uname",
    "whoami",
    "id",
    "date",
    "w",
    "who",
    "last",
    # Network info
    "netstat",
    "ss",
    "ip",
    "lsof",
    # Text processing
    "sort",
    "uniq",
    "cut",
    "tr",
    # System logs
    "journalctl",
    "sysctl",
}

FORBIDDEN_TOKENS: Set[str] = {
    # Output redirection (write operations)
    ">",
    ">>",
    "2>",
    "2>>",
    "&>",
    "&>>",
    "tee",
    # File manipulation
    "rm",
    "mv",
    "cp",
    "chmod",
    "chown",
    "chgrp",
    "chattr",
    "mkdir",
    "rmdir",
    "touch",
    # User management
    "useradd",
    "userdel",
    "usermod",
    "groupadd",
    "groupdel",
    "groupmod",
    "passwd",
    # Service control
    "systemctl",
    "service",
    "initctl",
    # System control
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    "init",
    # Process control
    "pkill",
    "kill",
    "killall",
    "skill",
    # Mount operations
    "mount",
    "umount",
    "swapon",
    "swapoff",
    # Output/write
    "echo",
    # Package managers
    "apt",
    "apt-get",
    "dpkg",
    "yum",
    "dnf",
    "zypper",
    "pacman",
    "rpm",
    "pip",
    "pip3",
    # Interpreters/compilers
    "python",
    "python3",
    "perl",
    "ruby",
    "node",
    "npm",
    "bash",
    "sh",
    "zsh",
    "csh",
    "tcsh",
    "ksh",
    "gcc",
    "g++",
    "make",
    "cmake",
    # Privilege escalation
    "sudo",
    "su",
    # Dangerous flags
    "-w",
    "--write",
    # Network configuration
    "ifconfig",
    "ifup",
    "ifdown",
    "iptables",
    "ip6tables",
    "firewall-cmd",
    "ufw",
    # Security
    "setenforce",
    "setsebool",
    # Scheduled tasks
    "crontab",
    # Editors
    "vi",
    "vim",
    "nano",
    "emacs",
    "ed",
}

SAFE_PATH_PREFIXES: Set[str] = {
    "/proc",
    "/sys",
    "/etc",
    "/var/log",
    "/usr/sap",
    "/hana",
    "/tmp",
}

# =============================================================================
# SSH Plugin Constants
# =============================================================================

# Whitelisted commands that are safe to execute on SAP VMs
SSH_SAFE_COMMANDS: Set[str] = {
    # System diagnostics
    "uptime",
    "hostname",
    "uname -a",
    "cat /etc/os-release",
    "df -h",
    "free -m",
    "top -bn1 | head -20",
    "ps aux | head -50",
    "systemctl status",
    "journalctl -n 100 --no-pager",
    # Network diagnostics
    "ip addr",
    "ip route",
    "ss -tulpn",
    "netstat -tulpn",
    # Pacemaker/Cluster
    "crm status",
    "crm_mon -1",
    "pcs status",
    "corosync-cfgtool -s",
    "corosync-quorumtool",
    "stonith_admin -L",
    "cibadmin --query --local",
    # SAP diagnostics
    "sapcontrol -nr {instance} -function GetProcessList",
    "sapcontrol -nr {instance} -function GetSystemInstanceList",
    "sapcontrol -nr {instance} -function GetVersionInfo",
    "HDB info",
    "hdbnsutil -sr_state",
    "hdbsql -U SYSTEM -j 'SELECT * FROM SYS.M_SYSTEM_OVERVIEW'",
    # Azure diagnostics
    "curl -s -H Metadata:true 'http://169.254.169.254/metadata/instance?api-version=2021-02-01'",
    "waagent --version",
}

# Command prefixes that are allowed (for parameterized commands)
SSH_SAFE_COMMAND_PREFIXES: Tuple[str, ...] = (
    "cat /var/log/",
    "cat /usr/sap/",
    "tail ",
    "head ",
    "grep ",
    "ls -la /",
    "ls -l /",
    "stat ",
    "file ",
    "wc -l ",
    "du -sh ",
    "find /var/log",
    "find /usr/sap",
    "journalctl ",
    "systemctl status ",
    "systemctl is-active ",
    "sapcontrol ",
    "hdbsql ",
    "sudo crm ",
    "sudo pcs ",
    "sudo corosync",
    "sudo stonith",
    "sudo cibadmin",
)

# Explicitly blocked patterns for SSH commands
SSH_BLOCKED_PATTERNS: Tuple[str, ...] = (
    "rm ",
    "mv ",
    "cp ",
    "chmod ",
    "chown ",
    "dd ",
    "mkfs",
    "fdisk",
    "parted",
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    "init ",
    "systemctl stop",
    "systemctl disable",
    "systemctl mask",
    "kill ",
    "pkill ",
    "killall ",
    "> ",
    ">> ",
    "| rm",
    "; rm",
    "&& rm",
    "curl.*-X POST",
    "curl.*-X PUT",
    "curl.*-X DELETE",
    "wget.*-O",
    "pip ",
    "apt ",
    "yum ",
    "dnf ",
    "zypper ",
    "passwd",
    "useradd",
    "userdel",
    "groupadd",
    "groupdel",
)

# =============================================================================
# Execution Plugin Constants
# =============================================================================

TEST_GROUP_PLAYBOOKS: Dict[str, str] = {
    "HA_DB_HANA": "playbook_00_ha_db_functional_tests.yml",
    "HA_SCS": "playbook_00_ha_scs_functional_tests.yml",
    "HA_OFFLINE": "playbook_01_ha_offline_tests.yml",
    "CONFIG_CHECKS": "playbook_00_configuration_checks.yml",
}

LOG_WHITELIST: Dict[Tuple[str, str], str] = {
    ("db", "hana_trace"): "/usr/sap/{sid}/HDB{instance}/*/trace/indexserver*.trc",
    ("db", "hana_alert"): "/usr/sap/{sid}/HDB{instance}/*/trace/*alert*.trc",
    ("scs", "sap_log"): "/usr/sap/{sid}/*/work/dev_*",
    ("app", "sap_log"): "/usr/sap/{sid}/*/work/dev_*",
    ("system", "messages"): "/var/log/messages",
    ("system", "syslog"): "/var/log/syslog",
}

# =============================================================================
# SSH Connection Defaults
# =============================================================================

DEFAULT_SSH_USER: str = "azureadm"
DEFAULT_SSH_TIMEOUT: int = 30
DEFAULT_SSH_PORT: int = 22

DEFAULT_SSH_OPTIONS: Tuple[str, ...] = (
    "-o StrictHostKeyChecking=no",
    "-o UserKnownHostsFile=/dev/null",
    "-o BatchMode=yes",
    "-o LogLevel=ERROR",
)
