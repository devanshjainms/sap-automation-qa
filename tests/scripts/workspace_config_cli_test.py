# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Contract tests for the workspace configuration command adapter."""

import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_ROOT / "src" / "core" / "generate_workspace_config.py"


def test_generator_help_is_available_as_a_standalone_script() -> None:
    """Expose the supported command adapter without activating the test runner."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0
    assert "--workspace-id" in result.stdout
    assert "--yes" in result.stdout


def test_generator_noninteractive_mode_requires_explicit_credential_source() -> None:
    """Fail before Azure discovery when a noninteractive credential is omitted."""
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--workspace-id",
            "DEV-EUS2-SAP01-SH7",
            "--resource-group",
            "rg",
            "--scs-vm",
            "scs01",
            "--db-vm",
            "db01",
            "--yes",
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 1
    assert "Choose --ssh-key" in result.stderr
