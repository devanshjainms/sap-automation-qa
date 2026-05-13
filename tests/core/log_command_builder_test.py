# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for LogCommandBuilder."""

import pytest
from src.core.execution.log_command_builder import LogCommandBuilder

_VARS = {"db_sid": "HDB", "db_instance_number": "00"}


class TestInit:
    def test_missing_access_method_raises(self) -> None:
        with pytest.raises(ValueError, match="access_method is required"):
            LogCommandBuilder({}, {})

    def test_invalid_access_method_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown access_method"):
            LogCommandBuilder({"access_method": "ftp"}, {})


class TestBuildFile:
    def test_simple_tail(self) -> None:
        b = LogCommandBuilder(
            {"access_method": "file", "path_template": "/var/log/messages"},
            {},
        )
        assert b.build() == "tail -100 /var/log/messages"

    def test_with_pattern(self) -> None:
        b = LogCommandBuilder(
            {"access_method": "file", "path_template": "/var/log/messages"},
            {},
        )
        cmd = b.build(pattern="error")
        assert "grep -iE 'error'" in cmd

    def test_with_time_window_date(self) -> None:
        b = LogCommandBuilder(
            {"access_method": "file", "path_template": "/var/log/messages"},
            {},
        )
        cmd = b.build(time_window="2026-04-10")
        assert "grep '2026-04-10'" in cmd

    def test_with_time_range(self) -> None:
        b = LogCommandBuilder(
            {"access_method": "file", "path_template": "/var/log/messages"},
            {},
        )
        cmd = b.build(time_window="2026-04-10 14:00 to 2026-04-10 15:00")
        assert "grep '2026-04-10'" in cmd

    def test_with_last_time_window(self) -> None:
        b = LogCommandBuilder(
            {"access_method": "file", "path_template": "/var/log/messages"},
            {},
        )
        cmd = b.build(time_window="last 30 min")
        assert cmd == "tail -100 /var/log/messages"

    def test_with_time_and_pattern(self) -> None:
        b = LogCommandBuilder(
            {"access_method": "file", "path_template": "/var/log/messages"},
            {},
        )
        cmd = b.build(time_window="2026-04-10", pattern="kernel")
        assert "grep '2026-04-10'" in cmd
        assert "grep -iE 'kernel'" in cmd

    def test_missing_path_raises(self) -> None:
        b = LogCommandBuilder({"access_method": "file"}, {})
        with pytest.raises(ValueError, match="path_template is required"):
            b.build()

    def test_path_placeholder_resolution(self) -> None:
        b = LogCommandBuilder(
            {"access_method": "file", "path_template": "/hana/<sid>/trace"},
            {"db_sid": "HDB"},
        )
        cmd = b.build()
        assert "/hana/hdb/trace" in cmd

    def test_sid_upper_placeholder(self) -> None:
        b = LogCommandBuilder(
            {"access_method": "file", "path_template": "/usr/sap/<SID>/HDB<NR>"},
            {"db_sid": "HDB", "db_instance_number": "00"},
        )
        cmd = b.build()
        assert "/usr/sap/HDB/HDB00" in cmd

    def test_max_lines(self) -> None:
        b = LogCommandBuilder(
            {"access_method": "file", "path_template": "/var/log/messages"},
            {},
        )
        cmd = b.build(max_lines=50)
        assert "tail -50" in cmd


class TestBuildJournalctl:
    def test_default(self) -> None:
        b = LogCommandBuilder({"access_method": "journalctl"}, {})
        cmd = b.build()
        assert cmd.startswith("journalctl")
        assert "--since '1 hour ago'" in cmd
        assert "--no-pager" in cmd

    def test_with_units(self) -> None:
        b = LogCommandBuilder(
            {"access_method": "journalctl", "service_units": ["corosync", "pacemaker"]},
            {},
        )
        cmd = b.build()
        assert "-u corosync" in cmd
        assert "-u pacemaker" in cmd

    def test_with_last_time_window(self) -> None:
        b = LogCommandBuilder({"access_method": "journalctl"}, {})
        cmd = b.build(time_window="last 30 min")
        assert "--since '30 min ago'" in cmd

    def test_with_time_range(self) -> None:
        b = LogCommandBuilder({"access_method": "journalctl"}, {})
        cmd = b.build(time_window="14:00 to 15:00")
        assert "--since '14:00'" in cmd
        assert "--until '15:00'" in cmd

    def test_with_plain_timestamp(self) -> None:
        b = LogCommandBuilder({"access_method": "journalctl"}, {})
        cmd = b.build(time_window="2026-04-10")
        assert "--since '2026-04-10'" in cmd

    def test_with_pattern(self) -> None:
        b = LogCommandBuilder({"access_method": "journalctl"}, {})
        cmd = b.build(pattern="error")
        assert "grep -iE 'error'" in cmd


class TestBuildGrepFilter:
    def test_basic(self) -> None:
        b = LogCommandBuilder(
            {
                "access_method": "grep_filter",
                "base_filter": "sbd",
                "path_template": "/var/log/messages",
            },
            {},
        )
        cmd = b.build()
        assert "grep -iE 'sbd' /var/log/messages" in cmd

    def test_missing_base_filter_raises(self) -> None:
        b = LogCommandBuilder(
            {"access_method": "grep_filter", "path_template": "/var/log/messages"},
            {},
        )
        with pytest.raises(ValueError, match="base_filter is required"):
            b.build()

    def test_with_time_and_pattern(self) -> None:
        b = LogCommandBuilder(
            {
                "access_method": "grep_filter",
                "base_filter": "sbd",
                "path_template": "/var/log/messages",
            },
            {},
        )
        cmd = b.build(time_window="14:00", pattern="timeout")
        assert "grep '14:00'" in cmd
        assert "grep -iE 'timeout'" in cmd

    def test_default_path(self) -> None:
        b = LogCommandBuilder(
            {"access_method": "grep_filter", "base_filter": "corosync"},
            {},
        )
        cmd = b.build()
        assert "/var/log/messages" in cmd


class TestBuildDmesg:
    def test_basic(self) -> None:
        b = LogCommandBuilder({"access_method": "dmesg"}, {})
        cmd = b.build()
        assert cmd.startswith("dmesg -T")

    def test_with_pattern(self) -> None:
        b = LogCommandBuilder({"access_method": "dmesg"}, {})
        cmd = b.build(pattern="oom")
        assert "grep -iE 'oom'" in cmd

    def test_with_time_window(self) -> None:
        b = LogCommandBuilder({"access_method": "dmesg"}, {})
        cmd = b.build(time_window="14:00")
        assert "grep '14:00'" in cmd


class TestRunAs:
    def test_root_no_wrap(self) -> None:
        b = LogCommandBuilder(
            {"access_method": "dmesg", "run_as": "root"},
            {},
        )
        cmd = b.build()
        assert "su -" not in cmd

    def test_non_root_wraps_with_su(self) -> None:
        b = LogCommandBuilder(
            {"access_method": "dmesg", "run_as": "<sid>adm"},
            {"db_sid": "HDB"},
        )
        cmd = b.build()
        assert "su - hdbadm -c" in cmd

    def test_default_is_root(self) -> None:
        b = LogCommandBuilder({"access_method": "dmesg"}, {})
        cmd = b.build()
        assert "su -" not in cmd
