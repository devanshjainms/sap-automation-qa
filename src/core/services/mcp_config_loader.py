# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Loader for ``WORKSPACES/CONFIG/mcp_servers.yaml``."""

import logging
from pathlib import Path
from typing import Optional
import yaml
from src.core.models.mcp_config import McpServersConfig

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path("WORKSPACES/CONFIG/mcp_servers.yaml")


def load_mcp_servers_config(
    config_path: Optional[Path] = None,
) -> McpServersConfig:
    """Load external MCP server configuration from YAML.

    Returns an empty config (no servers) if the file does not exist
    or is invalid.  The application starts successfully either way.

    :param config_path: Path to the YAML config file.
    :returns: Parsed MCP servers configuration.
    """
    path = config_path or _DEFAULT_CONFIG_PATH

    if not path.exists():
        logger.info("No MCP servers config at %s — no external servers", path)
        return McpServersConfig()

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not raw:
            return McpServersConfig()
        config = McpServersConfig.model_validate(raw)
        logger.info(
            "Loaded %d MCP server(s) from %s (%d enabled)",
            len(config.servers),
            path,
            len(config.enabled_servers),
        )
        return config
    except Exception as exc:
        logger.warning("Failed to parse MCP servers config at %s: %s", path, exc)
        return McpServersConfig()
