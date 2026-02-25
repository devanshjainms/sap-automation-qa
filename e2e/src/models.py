# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Result models for E2E release validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class Outcome(str, Enum):
    """Result of a single test execution."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"
    TIMEOUT = "timeout"


@dataclass
class TestResult:
    """Result of one test-group execution on one workspace.

    :param workspace_id: Workspace identifier.
    :param test_group: Test group name.
    :param outcome: Pass/fail/skip/error/timeout.
    :param duration_seconds: Wall-clock seconds.
    :param stdout: Captured stdout (truncated).
    :param stderr: Captured stderr (truncated).
    :param error_message: Human-readable error if any.
    :param ansible_return_code: Ansible exit code.
    :param report_path: Path to HTML report on the VM.
    """

    workspace_id: str = ""
    test_group: str = ""
    outcome: Outcome = Outcome.SKIPPED
    duration_seconds: float = 0.0
    stdout: str = ""
    stderr: str = ""
    error_message: str = ""
    ansible_return_code: int = -1
    report_path: str = ""


@dataclass
class DeployerResult:
    """Aggregated results for one deployer VM.

    :param distro: Linux distribution name.
    :param execution_mode: Execution mode (local or container).
    :param vm_name: Azure VM resource name.
    :param private_ip: Private IP address.
    :param setup_outcome: Outcome of setup.sh execution.
    :param setup_duration_seconds: Seconds for setup.sh.
    :param setup_stdout: Setup stdout.
    :param setup_stderr: Setup stderr.
    :param workspaces_discovered: Workspace IDs found on this VM.
    :param test_results: Per-workspace per-test-group results.
    :param started_at: When this deployer run started.
    :param finished_at: When this deployer run finished.
    """

    distro: str = ""
    execution_mode: str = ""
    vm_name: str = ""
    private_ip: str = ""
    setup_outcome: Outcome = Outcome.SKIPPED
    setup_duration_seconds: float = 0.0
    setup_stdout: str = ""
    setup_stderr: str = ""
    workspaces_discovered: list[str] = field(
        default_factory=list
    )
    test_results: list[TestResult] = field(
        default_factory=list
    )
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    @property
    def passed(self) -> int:
        """Count of passed tests."""
        return sum(
            1 for r in self.test_results
            if r.outcome == Outcome.PASSED
        )

    @property
    def failed(self) -> int:
        """Count of failed tests."""
        return sum(
            1 for r in self.test_results
            if r.outcome == Outcome.FAILED
        )

    @property
    def errors(self) -> int:
        """Count of errored tests."""
        return sum(
            1 for r in self.test_results
            if r.outcome == Outcome.ERROR
        )

    @property
    def total(self) -> int:
        """Total test count."""
        return len(self.test_results)

    @property
    def all_passed(self) -> bool:
        """True if all tests passed."""
        return self.total > 0 and self.failed == 0 and self.errors == 0


@dataclass
class E2ERunResult:
    """Top-level result of the entire E2E validation run.

    :param run_id: Unique identifier for this run.
    :param github_ref: Git ref that was tested.
    :param started_at: Run start time.
    :param finished_at: Run end time.
    :param deployer_results: Per-distro results.
    :param metadata: Extra context (workflow URL, etc.).
    """

    run_id: str = ""
    github_ref: str = ""
    started_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    finished_at: Optional[datetime] = None
    deployer_results: list[DeployerResult] = field(
        default_factory=list
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def all_passed(self) -> bool:
        """True if every deployer passed all tests.

        Returns ``False`` when no deployers were created,
        preventing a vacuously-true empty ``all()``.
        """
        return (
            len(self.deployer_results) > 0
            and all(
                d.all_passed for d in self.deployer_results
            )
        )

    @property
    def total_tests(self) -> int:
        """Total tests across all deployers."""
        return sum(d.total for d in self.deployer_results)

    @property
    def total_passed(self) -> int:
        """Total passed across all deployers."""
        return sum(
            d.passed for d in self.deployer_results
        )

    @property
    def total_failed(self) -> int:
        """Total failed across all deployers."""
        return sum(
            d.failed for d in self.deployer_results
        )

    def summary_line(self) -> str:
        """One-line summary for CI logs.

        :returns: Human-readable summary.
        :rtype: str
        """
        status = "PASSED" if self.all_passed else "FAILED"
        return (
            f"E2E {status}: "
            f"{self.total_passed}/{self.total_tests} "
            f"tests passed across "
            f"{len(self.deployer_results)} deployer(s)"
        )
