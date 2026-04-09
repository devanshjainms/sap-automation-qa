# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Data-driven log command builder.

Constructs shell commands from structured ``metadata`` on
:class:`~src.core.models.knowledge.EvidenceCollectorDef` objects.
All behaviour is driven by metadata fields — zero hardcoding.

Supported metadata keys
-----------------------
- **access_method** — ``file`` | ``journalctl`` | ``grep_filter`` | ``dmesg``
- **path_template** — Filesystem path with ``<SID>``, ``<NR>``, ``$(hostname)``
- **timestamp_format** — ``iso`` | ``syslog`` | ``hana``
- **run_as** — OS user (e.g. ``root`` or ``<sid>adm``)
- **service_units** — Systemd units for journalctl
- **base_filter** — Default grep pattern for ``grep_filter`` sources
- **key_patterns** — Informational grep patterns (passed through)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_VALID_ACCESS_METHODS = {"file", "journalctl", "grep_filter", "dmesg"}


class LogCommandBuilder:
    """Build executable shell commands from evidence-definition metadata.

    :param metadata: Structured metadata from an ``EvidenceCollectorDef``.
    :param extra_vars: Workspace parameters for placeholder resolution.
    :raises ValueError: If ``access_method`` is missing or unsupported.

    Usage::

        builder = LogCommandBuilder(evidence_def.metadata, workspace_params)
        cmd = builder.build(time_window="last 30 min", pattern="error")
    """

    def __init__(
        self,
        metadata: dict[str, Any],
        extra_vars: dict[str, Any],
    ) -> None:
        access_method = metadata.get("access_method", "")
        if not access_method:
            raise ValueError("metadata.access_method is required")
        if access_method not in _VALID_ACCESS_METHODS:
            raise ValueError(
                f"Unknown access_method '{access_method}'. "
                f"Must be one of: {sorted(_VALID_ACCESS_METHODS)}"
            )
        self._metadata = metadata
        self._extra_vars = extra_vars
        self._access_method = access_method

    def build(
        self,
        time_window: str = "",
        pattern: str = "",
        max_lines: int = 100,
    ) -> str:
        """Build a ready-to-execute shell command.

        :param time_window: Time range (e.g. ``last 30 min``,
            ``14:00 to 14:30``).
        :param pattern: Additional grep pattern.
        :param max_lines: Maximum output lines.
        :returns: Shell command string.
        """
        dispatch = {
            "file": self._build_file,
            "journalctl": self._build_journalctl,
            "grep_filter": self._build_grep_filter,
            "dmesg": self._build_dmesg,
        }
        inner = dispatch[self._access_method](time_window, pattern, max_lines)
        return self._wrap_run_as(inner)

    def _build_file(self, time_window: str, pattern: str, max_lines: int) -> str:
        """Direct file access via tail/grep."""
        path = self._resolve_path()
        if not path:
            raise ValueError("metadata.path_template is required for file access")
        if time_window and pattern:
            return (
                f"grep '{time_window.strip()}' {path}"
                f" | grep -iE '{pattern}' | tail -{max_lines}"
            )
        if time_window:
            return f"grep '{time_window.strip()}' {path} | tail -{max_lines}"
        if pattern:
            return f"grep -iE '{pattern}' {path} | tail -{max_lines}"
        return f"tail -{max_lines} {path}"

    def _build_journalctl(self, time_window: str, pattern: str, max_lines: int) -> str:
        """Journalctl with optional service/time/pattern."""
        parts = ["journalctl"]
        for unit in self._metadata.get("service_units", []):
            parts.append(f"-u {unit}")

        if time_window:
            tw = time_window.strip()
            if tw.startswith("last "):
                parts.append(f"--since '{tw[5:]} ago'")
            elif " to " in tw:
                since, until = tw.split(" to ", 1)
                parts.append(f"--since '{since.strip()}'")
                parts.append(f"--until '{until.strip()}'")
            else:
                parts.append(f"--since '{tw}'")
        else:
            parts.append("--since '1 hour ago'")

        parts.append("--no-pager")
        cmd = " ".join(parts)
        if pattern:
            cmd += f" | grep -iE '{pattern}'"
        cmd += f" | tail -{max_lines}"
        return cmd

    def _build_grep_filter(self, time_window: str, pattern: str, max_lines: int) -> str:
        """Grep-based filter for syslog sources (SBD, corosync)."""
        path = self._resolve_path() or "/var/log/messages"
        base_filter = self._metadata.get("base_filter", "")
        if not base_filter:
            raise ValueError("metadata.base_filter is required for grep_filter access")
        cmd = f"grep -iE '{base_filter}' {path}"
        if time_window:
            cmd += f" | grep '{time_window.strip()}'"
        if pattern:
            cmd += f" | grep -iE '{pattern}'"
        cmd += f" | tail -{max_lines}"
        return cmd

    def _build_dmesg(self, time_window: str, pattern: str, max_lines: int) -> str:
        """Kernel ring buffer via dmesg."""
        cmd = "dmesg -T"
        if time_window:
            cmd += f" | grep '{time_window.strip()}'"
        if pattern:
            cmd += f" | grep -iE '{pattern}'"
        cmd += f" | tail -{max_lines}"
        return cmd

    def _wrap_run_as(self, inner: str) -> str:
        """Wrap with ``su`` if ``run_as`` is a non-root user."""
        run_as = self._resolve_placeholder(self._metadata.get("run_as", "root"))
        if run_as and run_as != "root":
            return f"su - {run_as} -c '{inner}'"
        return inner

    def _resolve_path(self) -> str:
        """Resolve ``path_template`` with workspace placeholders."""
        return self._resolve_placeholder(self._metadata.get("path_template", ""))

    def _resolve_placeholder(self, value: str) -> str:
        """Substitute ``<sid>``, ``<SID>``, ``<NR>`` from workspace vars."""
        if not value:
            return value
        sid = self._extra_vars.get("db_sid") or self._extra_vars.get("sap_sid") or ""
        db_nr = str(self._extra_vars.get("db_instance_number", "")).strip('"').strip("'")
        scs_nr = str(self._extra_vars.get("scs_instance_number", "")).strip('"').strip("'")
        nr = db_nr or scs_nr or ""
        if sid:
            value = value.replace("<sid>", sid.lower())
            value = value.replace("<SID>", sid.upper())
        if nr:
            value = value.replace("<NR>", nr)
        return value
