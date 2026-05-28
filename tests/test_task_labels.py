# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Validate Ansible task label consistency across playbooks and roles.
"""

import re
from pathlib import Path
import pytest

SRC_DIR = Path(__file__).resolve().parent.parent / "src"

PLAYBOOK_PREFIXES = {"Init:", "Orchestration:", "Report:", "Telemetry:"}

ROLE_PREFIXES = {
    "Test Setup:",
    "Pre Validation:",
    "Test Execution:",
    "Post Validation:",
    "Rescue:",
    "Telemetry:",
    "Report:",
}


def _collect_task_names_from_yaml(filepath: Path) -> list[tuple[int, str]]:
    """Extract (line_number, name_value) pairs from task name: fields.

    Matches task-level name fields (``- name:`` with leading whitespace).
    Skips play-level names, loop variable names, and include_role/vars
    name parameters by checking indent depth and next-line context.

    :param filepath: Path to the YAML file.
    :returns: List of (line_number, task_name) tuples.
    """
    results = []
    content = filepath.read_text(encoding="utf-8")
    lines = content.splitlines()
    for line_num, line in enumerate(lines, start=1):
        match = re.match(r"(\s+)-\s*name:\s*(.+)", line)
        if not match:
            continue
        indent = len(match.group(1))
        name_val = match.group(2).strip().strip('"').strip("'")
        if not name_val or indent < 4:
            continue
        next_line = lines[line_num] if line_num < len(lines) else ""
        next_stripped = next_line.strip()
        if next_stripped.startswith(("tasks_from:", "file:", "hosts:")):
            continue
        results.append((line_num, name_val))
    return results


def _get_playbook_files() -> list[Path]:
    """Return all top-level playbook YAML files."""
    return sorted(SRC_DIR.glob("playbook_*.yml"))


def _get_role_task_files() -> list[Path]:
    """Return all role task YAML files across all role directories."""
    role_dirs = [
        "ha_db_hana",
        "ha_scs",
        "backup_db_hana",
        "misc",
        "configuration_checks",
    ]
    files = []
    for role_dir in role_dirs:
        task_dir = SRC_DIR / "roles" / role_dir / "tasks"
        if task_dir.exists():
            files.extend(sorted(task_dir.rglob("*.yml")))
    return files


class TestPlaybookLabels:
    """Validate playbook task labels follow the Init/Orchestration/Report taxonomy."""

    @pytest.fixture
    def playbook_files(self) -> list[Path]:
        """Collect playbook files.

        :returns: List of Path objects for all ``playbook_*.yml`` files.
        """
        files = _get_playbook_files()
        assert files, "No playbook files found"
        return files

    def test_playbook_tasks_have_phase_prefix(self, playbook_files: list[Path]) -> None:
        """Every playbook task name must start with a recognized phase prefix.

        :param playbook_files: Playbook file paths provided by the fixture.
        """
        violations = []
        for filepath in playbook_files:
            task_names = _collect_task_names_from_yaml(filepath)
            for line_num, name in task_names:
                if not any(name.startswith(prefix) for prefix in PLAYBOOK_PREFIXES):
                    violations.append(f"{filepath.name}:{line_num}: {name}")

        assert not violations, (
            f"Playbook tasks missing phase prefix "
            f"({', '.join(sorted(PLAYBOOK_PREFIXES))}):\n" + "\n".join(violations)
        )


class TestRoleLabels:
    """Validate role task labels follow the phase-based prefix taxonomy."""

    @pytest.fixture
    def role_files(self) -> list[Path]:
        """Collect role task files.

        :returns: List of Path objects for all role task YAML files.
        """
        files = _get_role_task_files()
        assert files, "No role task files found"
        return files

    def test_no_old_generic_labels(self, role_files: list[Path]) -> None:
        """Old generic labels like 'Test Setup Tasks' must not exist.

        :param role_files: Role task file paths provided by the fixture.
        """
        old_labels = [
            "Test Setup Tasks",
            "Rescue operation",
        ]
        violations = []
        for filepath in role_files:
            task_names = _collect_task_names_from_yaml(filepath)
            for line_num, name in task_names:
                for old_label in old_labels:
                    if name == old_label:
                        violations.append(
                            f"{filepath.relative_to(SRC_DIR)}:{line_num}: "
                            f"old generic label '{name}'"
                        )

        assert (
            not violations
        ), "Old generic labels found (should use phase prefix + dynamic name):\n" + "\n".join(
            violations
        )


class TestConfigChecksLabels:
    """Validate configuration checks have no hardcoded test group names."""

    def test_no_hardcoded_config_checks_name(self) -> None:
        """Config checks role must not hardcode 'ConfigurationChecks' string."""
        config_main = SRC_DIR / "roles" / "configuration_checks" / "tasks" / "main.yml"
        if not config_main.exists():
            pytest.skip("Configuration checks main.yml not found")

        content = config_main.read_text(encoding="utf-8")
        matches = []
        for line_num, line in enumerate(content.splitlines(), start=1):
            if '"ConfigurationChecks"' in line or "'ConfigurationChecks'" in line:
                matches.append(f"Line {line_num}: {line.strip()}")

        assert not matches, (
            "Hardcoded 'ConfigurationChecks' found in config checks role "
            "(use '{{ test_group_name }}'):\n" + "\n".join(matches)
        )
