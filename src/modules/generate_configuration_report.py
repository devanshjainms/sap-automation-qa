# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Standalone module to generate configuration check reports with execution logs.

This module reads test results and Ansible execution logs, then generates
a comprehensive HTML report that includes both configuration validation
results and execution metadata (timing, failures, task flow).
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import jinja2
from ansible.module_utils.basic import AnsibleModule

try:
    from ansible.module_utils.sap_automation_qa import SapAutomationQA
    from ansible.module_utils.enums import TestStatus
except ImportError:
    from src.module_utils.sap_automation_qa import SapAutomationQA
    from src.module_utils.enums import TestStatus

DOCUMENTATION = r"""
---
module: generate_configuration_report
short_description: Generate HTML reports with test results and execution logs
description:
    - Reads configuration check test results from playbook execution
    - Reads Ansible execution logs from callback plugin output
    - Merges both datasets and generates comprehensive HTML report
    - Includes timing data, task flow, failures, and test results
options:
    test_group_invocation_id:
        description: Unique identifier for the test group invocation
        type: str
        required: true
    test_group_name:
        description: Name of the test group
        type: str
        required: true
    workspace_directory:
        description: Base directory where logs and reports are stored
        type: str
        required: true
    test_case_results:
        description: Configuration check test results from playbook
        type: list
        required: false
    system_info:
        description: SAP system metadata for report context
        type: dict
        required: false
    execution_log_path:
        description: Path to Ansible execution log (JSONL format)
        type: str
        required: false
author:
    - Microsoft Corporation
"""

EXAMPLES = r"""
- name: Generate configuration report with execution logs
  generate_configuration_report:
    test_group_invocation_id: "{{ test_group_invocation_id }}"
    test_group_name: "CONFIG_{{ sap_sid | upper }}_{{ platform | upper }}"
    workspace_directory: "{{ _workspace_directory }}"
    test_case_results: "{{ all_results }}"
    system_info: "{{ system_info }}"
    execution_log_path: "{{ _workspace_directory }}/execution_log_*.json"
  register: report_result
"""


class ExecutionLogParser:
    """
    Parses Ansible execution logs from callback plugin output.

    Reads JSONL format logs and extracts:
    - Playbook and play boundaries
    - Task timing and status
    - Host-specific results
    - Aggregate statistics
    """

    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.logger = logging.getLogger(__name__)

    def parse(self) -> Dict[str, Any]:
        """
        Parse execution log and return structured data.

        Returns:
            Dictionary with execution metadata:
            - playbook_info: Start time, name, duration
            - plays: List of plays with tasks
            - tasks: Detailed task execution data
            - stats: Aggregate statistics
            - timeline: Chronological event list
        """
        if not self.log_path.exists():
            self.logger.warning(f"Execution log not found: {self.log_path}")
            return self._empty_execution_data()

        try:
            events = self._read_jsonl(self.log_path)
            return self._structure_execution_data(events)
        except Exception as exc:
            self.logger.error(f"Failed to parse execution log: {exc}")
            return self._empty_execution_data()

    def _read_jsonl(self, path: Path) -> List[Dict[str, Any]]:
        """Read JSONL file and return list of events."""
        events = []
        with open(path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    self.logger.warning(f"Invalid JSON at line {line_num} in {path}: {exc}")
        return events

    def _structure_execution_data(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Transform flat event list into structured execution data.

        Args:
            events: List of execution events from log

        Returns:
            Structured execution data with plays, tasks, stats
        """
        playbook_info = {}
        plays = []
        tasks = []
        stats = {}
        current_play = None

        for event in events:
            event_type = event.get("event_type")

            if event_type == "playbook_start":
                playbook_info = {
                    "name": event.get("playbook_name"),
                    "path": event.get("playbook_path"),
                    "start_time": event.get("timestamp"),
                }

            elif event_type == "play_start":
                current_play = {
                    "name": event.get("play_name"),
                    "hosts": event.get("hosts", []),
                    "start_time": event.get("timestamp"),
                    "tasks": [],
                }
                plays.append(current_play)

            elif event_type == "task_start":
                pass

            elif event_type == "task_result":
                task_data = {
                    "sequence": event.get("task_sequence"),
                    "name": event.get("task_name"),
                    "action": event.get("task_action"),
                    "host": event.get("host"),
                    "status": event.get("status"),
                    "duration": event.get("duration_seconds"),
                    "timestamp": event.get("timestamp"),
                    "result": event.get("result", {}),
                    "play_name": event.get("play_name"),
                }
                tasks.append(task_data)

                if current_play and current_play["name"] == task_data["play_name"]:
                    current_play["tasks"].append(task_data)

            elif event_type == "playbook_stats":
                stats = {
                    "total_duration": event.get("total_duration_seconds"),
                    "total_tasks": event.get("total_tasks"),
                    "hosts": event.get("hosts_summary", {}),
                }
                if playbook_info and event.get("timestamp"):
                    playbook_info["end_time"] = event.get("timestamp")
                    playbook_info["duration"] = event.get("total_duration_seconds")

        return {
            "playbook_info": playbook_info,
            "plays": plays,
            "tasks": tasks,
            "stats": stats,
            "timeline": events,
        }

    def _empty_execution_data(self) -> Dict[str, Any]:
        """Return empty execution data structure."""
        return {
            "playbook_info": {},
            "plays": [],
            "tasks": [],
            "stats": {},
            "timeline": [],
        }


class ConfigurationReportGenerator(SapAutomationQA):
    """
    Generates HTML reports for configuration checks with execution context.

    Responsibilities:
    - Load and validate test results
    - Parse execution logs
    - Merge datasets
    - Render HTML report using Jinja2
    - Handle errors gracefully with clear messages
    """

    def __init__(
        self,
        test_group_invocation_id: str,
        test_group_name: str,
        workspace_directory: str,
        test_case_results: Optional[List[Dict[str, Any]]] = None,
        system_info: Optional[Dict[str, Any]] = None,
        execution_log_path: Optional[str] = None,
    ):
        """
        Initialize report generator.

        Args:
            test_group_invocation_id: Unique ID for this test run
            test_group_name: Human-readable test group name
            workspace_directory: Base directory for I/O
            test_case_results: Configuration check results
            system_info: SAP system metadata
            execution_log_path: Optional explicit execution log path
        """
        super().__init__()
        self.test_group_invocation_id = test_group_invocation_id
        self.test_group_name = test_group_name
        self.workspace_directory = Path(workspace_directory)
        self.test_case_results = test_case_results or []
        self.system_info = system_info or {}
        self.execution_log_path = execution_log_path

        self.result.update({"status": None, "report_path": None})

    def _find_execution_log(self) -> Optional[Path]:
        """
        Find the most recent execution log file.

        Returns:
            Path to execution log or None if not found
        """
        if self.execution_log_path:
            return Path(self.execution_log_path)

        log_pattern = "execution_log_*.json"
        log_files = sorted(self.workspace_directory.glob(log_pattern))

        if log_files:
            return log_files[-1]

        return None

    def _load_template(self) -> str:
        """
        Load Jinja2 HTML template for configuration checks.

        Returns:
            Template content as string
        """
        template_path = Path(__file__).parent.parent / "templates" / "config_checks_report.html"

        if not template_path.exists():
            raise FileNotFoundError(f"Report template not found: {template_path}")

        with open(template_path, "r", encoding="utf-8") as f:
            return f.read()

    def generate(self) -> None:
        """
        Generate the HTML report with test results and execution logs.

        Main orchestration method:
        1. Find and parse execution log
        2. Load report template
        3. Merge data
        4. Render HTML
        5. Write to workspace
        """
        try:
            execution_log_path = self._find_execution_log()
            execution_data = {}

            if execution_log_path:
                self.log(logging.INFO, f"Parsing execution log: {execution_log_path}")
                parser = ExecutionLogParser(execution_log_path)
                execution_data = parser.parse()
            else:
                self.log(
                    logging.WARNING, "No execution log found - report will not include timing data"
                )

            template_content = self._load_template()

            report_context = {
                "test_case_results": self.test_case_results,
                "system_info": self.system_info,
                "execution_data": execution_data,
                "report_generation_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
                "test_group_invocation_id": self.test_group_invocation_id,
            }

            report_path = self._render_report(template_content, report_context)

            self.result["status"] = TestStatus.SUCCESS.value
            self.result["report_path"] = str(report_path)
            self.log(logging.INFO, f"Configuration report generated: {report_path}")

        except Exception as exc:
            self.log(logging.ERROR, f"Failed to generate report: {exc}")
            self.handle_error(exc)

    def _render_report(self, template_content: str, context: Dict[str, Any]) -> Path:
        """
        Render HTML report from template and context.

        Args:
            template_content: Jinja2 template as string
            context: Template context variables

        Returns:
            Path to generated report file
        """
        report_dir = self.workspace_directory / "quality_assurance"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"{self.test_group_name}_{self.test_group_invocation_id}.html"

        html_content = jinja2.Template(template_content).render(context)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return report_path


def run_module() -> None:
    """
    Entry point when invoked as Ansible module.
    """

    module_args = dict(
        test_group_invocation_id=dict(type="str", required=True),
        test_group_name=dict(type="str", required=True),
        workspace_directory=dict(type="str", required=True),
        test_case_results=dict(type="list", required=False, default=[]),
        system_info=dict(type="dict", required=False, default={}),
        execution_log_path=dict(type="str", required=False),
    )

    module = AnsibleModule(argument_spec=module_args, supports_check_mode=False)

    generator = ConfigurationReportGenerator(
        test_group_invocation_id=module.params["test_group_invocation_id"],
        test_group_name=module.params["test_group_name"],
        workspace_directory=module.params["workspace_directory"],
        test_case_results=module.params.get("test_case_results"),
        system_info=module.params.get("system_info"),
        execution_log_path=module.params.get("execution_log_path"),
    )

    generator.generate()
    module.exit_json(**generator.get_result())


def run_standalone(args: List[str]) -> int:
    """
    Entry point when invoked as standalone script.
    
    Usage:
        python generate_configuration_report.py \\
            --invocation-id UUID \\
            --group-name "CONFIG_X01_HANA" \\
            --workspace /path/to/workspace \\
            --results-file /path/to/results.json \\
            --system-info-file /path/to/system_info.json
    
    Returns:
        Exit code (0 for success, 1 for failure)
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate configuration check HTML report with execution logs"
    )
    parser.add_argument("--invocation-id", required=True, help="Test group invocation ID (UUID)")
    parser.add_argument("--group-name", required=True, help="Test group name for report filename")
    parser.add_argument(
        "--workspace", required=True, help="Workspace directory containing logs and results"
    )
    parser.add_argument("--results-file", help="Path to test results JSON file")
    parser.add_argument("--system-info-file", help="Path to system info JSON file")
    parser.add_argument(
        "--execution-log", help="Explicit path to execution log (auto-detected if omitted)"
    )

    parsed_args = parser.parse_args(args)
    test_results = []
    if parsed_args.results_file:
        with open(parsed_args.results_file, "r", encoding="utf-8") as f:
            test_results = json.load(f)
    system_info = {}
    if parsed_args.system_info_file:
        with open(parsed_args.system_info_file, "r", encoding="utf-8") as f:
            system_info = json.load(f)
    generator = ConfigurationReportGenerator(
        test_group_invocation_id=parsed_args.invocation_id,
        test_group_name=parsed_args.group_name,
        workspace_directory=parsed_args.workspace,
        test_case_results=test_results,
        system_info=system_info,
        execution_log_path=parsed_args.execution_log,
    )

    generator.generate()
    result = generator.get_result()

    if result["status"] == "SUCCESS":
        print(f"Report generated: {result['report_path']}")
        return 0
    else:
        print(
            f"Report generation failed: {result.get('message', 'Unknown error')}", file=sys.stderr
        )
        return 1


def main() -> None:
    """Entry point dispatcher."""
    run_module()


if __name__ == "__main__":
    main()
