# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
HTML + GitHub Actions summary reporter for E2E validation results.
"""

from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from e2e.src.models import (
    E2ERunResult,
    Outcome,
)

logger = logging.getLogger(__name__)


class Reporter:
    """Generate reports from E2E run results.

    :param report_dir: Directory to write report files.
    """

    def __init__(self, report_dir: str = "e2e/reports") -> None:
        self._report_dir = Path(report_dir)
        self._report_dir.mkdir(parents=True, exist_ok=True)

    def generate_all(self, run_result: E2ERunResult) -> dict[str, str]:
        """Generate all report formats.

        :param run_result: Completed E2E run result.
        :returns: Mapping of report type to file path.
        :rtype: dict[str, str]
        """
        paths: dict[str, str] = {}

        html_path = self._generate_html(run_result)
        paths["html"] = str(html_path)

        junit_path = self._generate_junit(run_result)
        paths["junit"] = str(junit_path)

        self._write_github_summary(run_result)

        logger.info("Reports written to %s", self._report_dir)
        return paths

    def _generate_html(self, run: E2ERunResult) -> Path:
        """Generate a standalone HTML report.

        :param run: E2E run result.
        :returns: Path to the generated HTML file.
        :rtype: Path
        """
        rows = ""
        for dep in run.deployer_results:
            for tr in dep.test_results:
                css = _outcome_css(tr.outcome)
                rows += (
                    f"<tr class='{css}'>"
                    f"<td>{dep.distro}</td>"
                    f"<td>{dep.vm_name}</td>"
                    f"<td>{tr.workspace_id}</td>"
                    f"<td>{tr.test_group}</td>"
                    f"<td>{tr.outcome.value}</td>"
                    f"<td>{tr.duration_seconds:.1f}s</td>"
                    f"<td>{_escape(tr.error_message)}</td>"
                    f"</tr>\n"
                )

        setup_rows = ""
        for dep in run.deployer_results:
            css = _outcome_css(dep.setup_outcome)
            setup_rows += (
                f"<tr class='{css}'>"
                f"<td>{dep.distro}</td>"
                f"<td>{dep.vm_name}</td>"
                f"<td>{dep.setup_outcome.value}</td>"
                f"<td>{dep.setup_duration_seconds:.1f}s</td>"
                f"<td>{len(dep.workspaces_discovered)}</td>"
                f"</tr>\n"
            )

        status = "PASSED" if run.all_passed else "FAILED"
        status_css = "pass" if run.all_passed else "fail"
        duration = ""
        if run.finished_at and run.started_at:
            secs = (run.finished_at - run.started_at).total_seconds()
            duration = f"{secs:.0f}s"

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>E2E Release Validation — {status}</title>
<style>
  body {{ font-family: -apple-system, sans-serif; margin: 2em; }}
  h1 {{ color: #333; }}
  .summary {{ font-size: 1.2em; margin: 1em 0; }}
  .pass {{ color: #22863a; }}
  .fail {{ color: #cb2431; }}
  .skip {{ color: #6a737d; }}
  .error {{ color: #e36209; }}
  .timeout {{ color: #b08800; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
  th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
  th {{ background: #f6f8fa; }}
  tr.pass td:nth-child(5) {{ background: #dcffe4; }}
  tr.fail td:nth-child(5) {{ background: #ffdce0; }}
  tr.error td:nth-child(5) {{ background: #fff5b1; }}
  tr.skip td:nth-child(5) {{ background: #f1f1f1; }}
  tr.timeout td:nth-child(5) {{ background: #fff1cc; }}
  .meta {{ color: #586069; font-size: 0.9em; }}
</style>
</head>
<body>
<h1 class="{status_css}">E2E Release Validation — {status}</h1>

<div class="summary">
  <strong>Run ID:</strong> {run.run_id}<br>
  <strong>Git Ref:</strong> {run.github_ref}<br>
  <strong>Duration:</strong> {duration}<br>
  <strong>Tests:</strong> {run.total_passed}/{run.total_tests} passed,
    {run.total_failed} failed<br>
  <strong>Deployers:</strong> {len(run.deployer_results)}
</div>

<h2>Setup Results (per Deployer)</h2>
<table>
<tr>
  <th>Distro</th><th>VM</th><th>Outcome</th>
  <th>Duration</th><th>Workspaces</th>
</tr>
{setup_rows}
</table>

<h2>Test Results</h2>
<table>
<tr>
  <th>Distro</th><th>VM</th><th>Workspace</th>
  <th>Test Group</th><th>Outcome</th><th>Duration</th>
  <th>Error</th>
</tr>
{rows}
</table>

<div class="meta">
  Generated at {datetime.now(timezone.utc).isoformat()}
</div>
</body>
</html>"""

        path = self._report_dir / f"e2e-report-{run.run_id}.html"
        path.write_text(html, encoding="utf-8")
        logger.info("HTML report: %s", path)
        return path

    def _generate_junit(self, run: E2ERunResult) -> Path:
        """Generate JUnit XML for CI integration.

        :param run: E2E run result.
        :returns: Path to the JUnit XML file.
        :rtype: Path
        """
        testsuites = ET.Element("testsuites")
        testsuites.set("name", "E2E Release Validation")
        testsuites.set("tests", str(run.total_tests))
        testsuites.set("failures", str(run.total_failed))

        for dep in run.deployer_results:
            suite = ET.SubElement(testsuites, "testsuite")
            suite.set("name", f"deployer-{dep.distro}")
            suite.set("tests", str(dep.total))
            suite.set("failures", str(dep.failed))
            suite.set("errors", str(dep.errors))

            setup_tc = ET.SubElement(suite, "testcase")
            setup_tc.set("name", f"setup-{dep.distro}")
            setup_tc.set(
                "classname",
                f"e2e.deployer.{dep.distro}",
            )
            setup_tc.set(
                "time",
                f"{dep.setup_duration_seconds:.1f}",
            )
            if dep.setup_outcome not in (
                Outcome.PASSED,
                Outcome.SKIPPED,
            ):
                fail_el = ET.SubElement(setup_tc, "failure")
                fail_el.set(
                    "message",
                    f"Setup {dep.setup_outcome.value}",
                )
                fail_el.text = dep.setup_stderr[:2000]

            for tr in dep.test_results:
                tc = ET.SubElement(suite, "testcase")
                tc.set(
                    "name",
                    f"{tr.workspace_id}-{tr.test_group}",
                )
                tc.set(
                    "classname",
                    f"e2e.{dep.distro}.{tr.workspace_id}",
                )
                tc.set("time", f"{tr.duration_seconds:.1f}")

                if tr.outcome == Outcome.FAILED:
                    fail_el = ET.SubElement(tc, "failure")
                    fail_el.set("message", tr.error_message[:500])
                    fail_el.text = tr.stderr[:2000]
                elif tr.outcome == Outcome.ERROR:
                    err_el = ET.SubElement(tc, "error")
                    err_el.set("message", tr.error_message[:500])
                    err_el.text = tr.stderr[:2000]
                elif tr.outcome == Outcome.SKIPPED:
                    ET.SubElement(tc, "skipped")
                elif tr.outcome == Outcome.TIMEOUT:
                    fail_el = ET.SubElement(tc, "failure")
                    fail_el.set("message", "Timed out")
                    fail_el.text = tr.error_message[:2000]

        tree = ET.ElementTree(testsuites)
        path = self._report_dir / f"e2e-junit-{run.run_id}.xml"
        tree.write(
            str(path),
            encoding="unicode",
            xml_declaration=True,
        )
        logger.info("JUnit report: %s", path)
        return path

    def _write_github_summary(self, run: E2ERunResult) -> None:
        """Write a Markdown summary to $GITHUB_STEP_SUMMARY.

        :param run: E2E run result.
        """
        summary_file = os.getenv("GITHUB_STEP_SUMMARY")
        if not summary_file:
            logger.debug("GITHUB_STEP_SUMMARY not set; skipping")
            return

        status_emoji = ":white_check_mark:" if run.all_passed else ":x:"
        lines = [
            f"## {status_emoji} E2E Release Validation",
            "",
            f"**Run ID:** `{run.run_id}`",
            f"**Git Ref:** `{run.github_ref}`",
            f"**Tests:** {run.total_passed}/{run.total_tests} "
            f"passed, {run.total_failed} failed",
            "",
            "### Setup Results",
            "",
            "| Distro | VM | Outcome | Duration | Workspaces |",
            "|--------|----|---------|----------|------------|",
        ]

        for dep in run.deployer_results:
            lines.append(
                f"| {dep.distro} | {dep.vm_name} "
                f"| {dep.setup_outcome.value} "
                f"| {dep.setup_duration_seconds:.0f}s "
                f"| {len(dep.workspaces_discovered)} |"
            )

        lines.extend(
            [
                "",
                "### Test Results",
                "",
                "| Distro | Workspace | Test Group " "| Outcome | Duration | Error |",
                "|--------|-----------|------------|" "---------|----------|-------|",
            ]
        )

        for dep in run.deployer_results:
            for tr in dep.test_results:
                err = tr.error_message[:80].replace("|", "\\|")
                lines.append(
                    f"| {dep.distro} | {tr.workspace_id} "
                    f"| {tr.test_group} "
                    f"| {tr.outcome.value} "
                    f"| {tr.duration_seconds:.0f}s "
                    f"| {err} |"
                )

        summary_content = "\n".join(lines) + "\n"
        try:
            with open(summary_file, "a") as f:
                f.write(summary_content)
            logger.info("GitHub summary written")
        except OSError as exc:
            logger.warning("Failed to write GitHub summary: %s", exc)


def _outcome_css(outcome: Outcome) -> str:
    """Map outcome to CSS class.

    :param outcome: Test outcome.
    :returns: CSS class name.
    :rtype: str
    """
    return {
        Outcome.PASSED: "pass",
        Outcome.FAILED: "fail",
        Outcome.SKIPPED: "skip",
        Outcome.ERROR: "error",
        Outcome.TIMEOUT: "timeout",
    }.get(outcome, "")


def _escape(s: str) -> str:
    """HTML-escape a string.

    :param s: Input string.
    :returns: Escaped string.
    :rtype: str
    """
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
