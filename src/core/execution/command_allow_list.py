# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Command allow-list for triage evidence collection.

Only commands explicitly on the allow-list may be executed against
production SAP systems. Everything else is rejected. This is the
primary security boundary for the triage executor.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass(frozen=True)
class AllowedCommand:
    """A single command pattern permitted for evidence collection.

    :param pattern: Regex pattern matching the allowed command.
    :param description: Human-readable purpose of this command.
    :param source: Where this entry was loaded from.
    :param max_timeout_seconds: Maximum execution time allowed.
    """

    pattern: str
    description: str = ""
    source: str = ""
    max_timeout_seconds: int = 30


class CommandAllowList:
    """Maintains a set of allowed command patterns for triage.

    Only commands matching at least one pattern are permitted.
    The list is loaded from JSONL files (evidence definitions)
    and can be extended programmatically.

    :param entries: Initial set of allowed command entries.
    """

    def __init__(self, entries: Optional[list[AllowedCommand]] = None) -> None:
        self._entries: list[AllowedCommand] = list(entries) if entries else []
        self._compiled: list[re.Pattern[str]] = []
        self._recompile()

    @property
    def entries(self) -> list[AllowedCommand]:
        """Return a copy of all allowed command entries."""
        return list(self._entries)

    @property
    def count(self) -> int:
        """Number of allowed command patterns."""
        return len(self._entries)

    def add(self, entry: AllowedCommand) -> None:
        """Add a command pattern to the allow-list.

        :param entry: Command entry to add.
        """
        self._entries.append(entry)
        self._compiled.append(re.compile(entry.pattern, re.IGNORECASE))

    def is_allowed(self, command: str) -> bool:
        """Check whether a command is permitted.

        :param command: The raw command string to validate.
        :returns: True if at least one pattern matches.
        """
        if not command or not command.strip():
            return False
        stripped = command.strip()
        return any(p.search(stripped) for p in self._compiled)

    def get_timeout(self, command: str) -> int:
        """Return the maximum timeout for a matching command.

        :param command: The command string.
        :returns: Timeout in seconds, or 30 as the default.
        """
        stripped = command.strip()
        for entry, compiled in zip(self._entries, self._compiled):
            if compiled.search(stripped):
                return entry.max_timeout_seconds
        return 30

    def _recompile(self) -> None:
        """Recompile all regex patterns from the entries list."""
        self._compiled = [re.compile(e.pattern, re.IGNORECASE) for e in self._entries]

    @classmethod
    def from_patterns(cls, patterns: list[str]) -> "CommandAllowList":
        """Create an allow-list from simple pattern strings.

        :param patterns: List of regex pattern strings.
        :returns: A new CommandAllowList.
        """
        entries = [AllowedCommand(pattern=p) for p in patterns]
        return cls(entries=entries)

    @classmethod
    def from_yaml(cls, path: Path | str) -> "CommandAllowList":
        """Load an allow-list from a YAML file.

        Expected format::

            commands:
              - pattern: "^crm\\\\s+status"
                description: "CRM status"
                max_timeout_seconds: 30

        :param path: Path to the YAML file.
        :returns: A new CommandAllowList.
        :raises FileNotFoundError: If the file does not exist.
        :raises ValueError: If the YAML structure is invalid.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Allow-list file not found: {path}")

        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

        return cls._from_parsed_yaml(data, source=str(path))

    @classmethod
    def _from_parsed_yaml(cls, data: Any, source: str = "yaml") -> "CommandAllowList":
        """Build an allow-list from parsed YAML data.

        :param data: Parsed YAML dict with a ``commands`` key.
        :param source: Label for the source of these entries.
        :returns: A new CommandAllowList.
        :raises ValueError: If the structure is invalid.
        """
        if not isinstance(data, dict) or "commands" not in data:
            raise ValueError("YAML must contain a top-level 'commands' key")

        commands = data["commands"]
        if not isinstance(commands, list):
            raise ValueError("'commands' must be a list")

        entries: list[AllowedCommand] = []
        for item in commands:
            if not isinstance(item, dict) or "pattern" not in item:
                raise ValueError(f"Each command must be a dict with a 'pattern' key, got: {item}")
            entries.append(
                AllowedCommand(
                    pattern=item["pattern"],
                    description=item.get("description", ""),
                    source=source,
                    max_timeout_seconds=item.get("max_timeout_seconds", 30),
                )
            )
        return cls(entries=entries)

    @classmethod
    def default(cls) -> "CommandAllowList":
        """Load the default allow-list from the bundled YAML file.

        The default commands are defined in ``allowed_commands.yaml``
        alongside this module. Users can edit that file to add or
        remove commands without touching Python code.

        :returns: A CommandAllowList with the bundled safe commands.
        """
        yaml_path = Path(__file__).parent / "allowed_commands.yaml"
        return cls.from_yaml(yaml_path)
