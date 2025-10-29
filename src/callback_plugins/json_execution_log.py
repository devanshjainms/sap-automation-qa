# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Ansible callback plugin to capture execution logs as structured JSON.

This callback plugin captures all task execution data including timing,
status, host information, and results. It writes to a JSON file in the
workspace directory for post-execution analysis and reporting.

Design Principles:
- Enterprise-grade: Safe defaults, deterministic behavior, structured output
- Resilient: Handles missing attributes, filesystem errors gracefully
- Observability: Captures correlation IDs, timing data, task hierarchy
- Performance: Minimal overhead, buffered writes, async-friendly
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from ansible.plugins.callback import CallbackBase

DOCUMENTATION = """
callback: json_execution_log
type: aggregate
short_description: Capture structured execution logs for post-processing
description:
  - Captures all task execution events with timing and result data
  - Writes structured JSON to workspace for post-execution report generation
  - Includes play context, task metadata, host information, and results
  - Safe for production use with minimal performance impact
version_added: "1.0"
requirements:
  - Writable workspace directory
options:
  output_dir:
    description: Directory to write execution log file
    default: /tmp/sap_automation_qa
    env:
      - name: SAP_QA_WORKSPACE_DIR
    ini:
      - section: callback_json_execution_log
        key: output_dir
  log_file_prefix:
    description: Prefix for the execution log filename
    default: execution_log
    env:
      - name: SAP_QA_EXEC_LOG_PREFIX
    ini:
      - section: callback_json_execution_log
        key: log_file_prefix
"""


class CallbackModule(CallbackBase):
    """
    Ansible callback plugin to capture structured execution logs.

    Captures execution flow with enterprise-grade observability:
    - Task-level timing and status
    - Host-specific results
    - Play and playbook boundaries
    - Error and failure details
    - Resource consumption hints
    """

    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "aggregate"
    CALLBACK_NAME = "json_execution_log"
    CALLBACK_NEEDS_WHITELIST = False

    def __init__(self):
        super(CallbackModule, self).__init__()

        self.start_time = time.time()
        self.playbook_start_time: Optional[float] = None
        self.play_start_time: Optional[float] = None
        self.task_start_times: Dict[str, float] = {}

        self.execution_log: list = []
        self.playbook_name: Optional[str] = None
        self.current_play: Optional[str] = None
        self.task_counter = 0
        self.output_dir: Optional[Path] = None
        self.log_file_path: Optional[Path] = None
        self.invocation_id: Optional[str] = None

    def set_options(self, task_keys=None, var_options=None, direct=None):
        """
        Configure callback plugin options.

        Priority: direct params > environment vars > ansible.cfg > defaults
        """
        super(CallbackModule, self).set_options(
            task_keys=task_keys, var_options=var_options, direct=direct
        )
        output_dir_str = self.get_option("output_dir")
        if not output_dir_str:
            output_dir_str = os.environ.get("SAP_QA_WORKSPACE_DIR", "/tmp/sap_automation_qa")

        self.output_dir = Path(output_dir_str)
        log_prefix = self.get_option("log_file_prefix") or "execution_log"
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            log_file_name = f"{log_prefix}_{int(self.start_time)}.json"
            self.log_file_path = self.output_dir / log_file_name
        except (OSError, PermissionError) as exc:
            self._display.warning(
                f"Failed to create execution log directory {self.output_dir}: {exc}"
            )
            self.log_file_path = None

    def _write_log_entry(self, entry: Dict[str, Any]) -> None:
        """
        Write a single log entry to the JSON file.

        Uses append mode with one JSON object per line (JSONL format)
        for safe concurrent writes and streaming consumption.

        Args:
            entry: Dictionary containing log entry data
        """
        if not self.log_file_path:
            return

        try:
            with open(self.log_file_path, "a", encoding="utf-8") as log_file:
                json.dump(entry, log_file, ensure_ascii=False, default=str)
                log_file.write("\n")
        except (IOError, OSError) as exc:
            self._display.warning(f"Failed to write execution log: {exc}")

    def _get_task_key(self, task, host=None) -> str:
        """
        Generate unique key for task tracking.

        Args:
            task: Ansible task object
            host: Optional host name for host-specific tracking

        Returns:
            Unique string key for this task (+ host)
        """
        task_uuid = getattr(task, "_uuid", "unknown")
        if host:
            return f"{task_uuid}_{host}"
        return task_uuid

    def v2_playbook_on_start(self, playbook):
        """Capture playbook start event."""
        self.playbook_start_time = time.time()
        self.playbook_name = os.path.basename(playbook._file_name)

        entry = {
            "event_type": "playbook_start",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "playbook_name": self.playbook_name,
            "playbook_path": playbook._file_name,
        }
        self._write_log_entry(entry)

    def v2_playbook_on_play_start(self, play):
        """Capture play start event."""
        self.play_start_time = time.time()
        self.current_play = play.get_name()

        entry = {
            "event_type": "play_start",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "play_name": self.current_play,
            "hosts": [h.get_name() for h in play.hosts] if play.hosts else [],
        }
        self._write_log_entry(entry)

    def v2_playbook_on_task_start(self, task, is_conditional):
        """Capture task start event."""
        task_key = self._get_task_key(task)
        self.task_start_times[task_key] = time.time()
        self.task_counter += 1

        entry = {
            "event_type": "task_start",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "task_sequence": self.task_counter,
            "task_name": task.get_name(),
            "task_action": task.action,
            "task_uuid": str(getattr(task, "_uuid", "unknown")),
            "play_name": self.current_play,
            "is_conditional": is_conditional,
        }
        self._write_log_entry(entry)

    def v2_runner_on_ok(self, result):
        """Capture successful task completion."""
        self._process_task_result(result, "ok")

    def v2_runner_on_failed(self, result, ignore_errors=False):
        """Capture failed task."""
        self._process_task_result(result, "failed", ignore_errors=ignore_errors)

    def v2_runner_on_skipped(self, result):
        """Capture skipped task."""
        self._process_task_result(result, "skipped")

    def v2_runner_on_unreachable(self, result):
        """Capture unreachable host."""
        self._process_task_result(result, "unreachable")

    def _process_task_result(self, result, status: str, ignore_errors: bool = False):
        """
        Process and log task result.

        Args:
            result: Ansible task result object
            status: Task status (ok, failed, skipped, unreachable)
            ignore_errors: Whether errors are being ignored
        """
        task = result._task
        host = result._host.get_name()
        start_time = self.task_start_times.get(self._get_task_key(task))
        duration = time.time() - start_time if start_time else None
        result_data = {}
        if hasattr(result, "_result"):
            result_dict = result._result
            safe_fields = [
                "msg",
                "changed",
                "failed",
                "skipped",
                "rc",
                "stdout",
                "stderr",
                "stdout_lines",
                "stderr_lines",
                "ansible_facts",
                "results",
                "warnings",
            ]
            result_data = {k: v for k, v in result_dict.items() if k in safe_fields}
            for field in ["stdout", "stderr"]:
                if field in result_data and isinstance(result_data[field], str):
                    if len(result_data[field]) > 5000:
                        result_data[field] = (
                            result_data[field][:2500]
                            + "\n... [truncated] ...\n"
                            + result_data[field][-2500:]
                        )

        entry = {
            "event_type": "task_result",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "task_sequence": self.task_counter,
            "task_name": task.get_name(),
            "task_action": task.action,
            "task_uuid": str(getattr(task, "_uuid", "unknown")),
            "host": host,
            "status": status,
            "ignore_errors": ignore_errors,
            "duration_seconds": round(duration, 3) if duration else None,
            "play_name": self.current_play,
            "result": result_data,
        }
        self._write_log_entry(entry)

    def v2_playbook_on_stats(self, stats):
        """Capture final playbook statistics."""
        total_duration = time.time() - self.playbook_start_time if self.playbook_start_time else 0.0
        hosts_summary = {}
        for host in stats.processed.keys():
            hosts_summary[host] = {
                "ok": stats.ok.get(host, 0),
                "changed": stats.changed.get(host, 0),
                "failures": stats.failures.get(host, 0),
                "skipped": stats.skipped.get(host, 0),
                "unreachable": stats.dark.get(host, 0),
            }

        entry = {
            "event_type": "playbook_stats",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "playbook_name": self.playbook_name,
            "total_duration_seconds": round(total_duration, 3),
            "total_tasks": self.task_counter,
            "hosts_summary": hosts_summary,
        }
        self._write_log_entry(entry)

        if self.log_file_path:
            self._display.display(
                f"Execution log written to: {self.log_file_path}",
                color="green",
            )
