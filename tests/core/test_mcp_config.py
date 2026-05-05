# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for MCP server configuration model and loader."""

import tempfile
from pathlib import Path

import pytest

from src.core.models.mcp_config import (
    McpServerEntry,
    McpServersConfig,
    SafetyTier,
)
from src.core.services.mcp_config_loader import load_mcp_servers_config


class TestMcpServerEntry:
    """Tests for McpServerEntry model."""

    def test_defaults(self):
        entry = McpServerEntry(name="test", url="http://localhost:8001")
        assert entry.safety == SafetyTier.READ_ONLY
        assert entry.enabled is True
        assert entry.tool_allow_list is None
        assert entry.preamble_hint == ""

    def test_allow_all(self):
        entry = McpServerEntry(name="test", url="http://localhost:8001", tools={"allow": "all"})
        assert entry.tool_allow_list is None
        assert entry.tool_is_allowed("anything") is True

    def test_allow_list_filters(self):
        entry = McpServerEntry(
            name="azure",
            url="http://localhost:8001",
            tools={"allow": ["monitor", "compute"]},
        )
        assert entry.tool_allow_list == ["monitor", "compute"]
        assert entry.tool_is_allowed("monitor_query") is True
        assert entry.tool_is_allowed("compute_list") is True
        assert entry.tool_is_allowed("storage_blob") is False

    def test_safety_tiers(self):
        for tier in SafetyTier:
            entry = McpServerEntry(name="test", url="http://localhost", safety=tier)
            assert SafetyTier(entry.safety) == tier


class TestMcpServersConfig:
    """Tests for McpServersConfig model."""

    def test_empty(self):
        config = McpServersConfig()
        assert config.servers == []
        assert config.enabled_servers == []

    def test_enabled_servers_filters(self):
        config = McpServersConfig(
            servers=[
                McpServerEntry(name="a", url="http://a", enabled=True),
                McpServerEntry(name="b", url="http://b", enabled=False),
                McpServerEntry(name="c", url="http://c", enabled=True),
            ]
        )
        enabled = config.enabled_servers
        assert len(enabled) == 2
        assert {s.name for s in enabled} == {"a", "c"}


class TestLoadMcpServersConfig:
    """Tests for the YAML config loader."""

    def test_missing_file_returns_empty(self, tmp_path):
        config = load_mcp_servers_config(tmp_path / "nonexistent.yaml")
        assert config.servers == []

    def test_empty_file_returns_empty(self, tmp_path):
        f = tmp_path / "mcp_servers.yaml"
        f.write_text("")
        config = load_mcp_servers_config(f)
        assert config.servers == []

    def test_valid_config(self, tmp_path):
        f = tmp_path / "mcp_servers.yaml"
        f.write_text("""
servers:
  - name: azure
    url: http://localhost:8001
    auth: managed_identity
    safety: confirm_writes
    tools:
      allow:
        - monitor
        - compute
    preamble_hint: Use for Azure infra checks.
  - name: monitoring
    url: http://localhost:8002
    safety: read_only
    tools:
      allow: all
""")
        config = load_mcp_servers_config(f)
        assert len(config.servers) == 2
        azure = config.servers[0]
        assert azure.name == "azure"
        assert azure.safety == SafetyTier.CONFIRM_WRITES
        assert azure.tool_allow_list == ["monitor", "compute"]
        assert "Azure infra" in azure.preamble_hint

    def test_invalid_yaml_returns_empty(self, tmp_path):
        f = tmp_path / "mcp_servers.yaml"
        f.write_text("not: [valid: yaml: {broken")
        config = load_mcp_servers_config(f)
        assert config.servers == []
