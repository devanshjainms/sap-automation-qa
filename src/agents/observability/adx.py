# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Azure Data Explorer (Kusto) integration for service logs.
"""

from __future__ import annotations
import json
import logging
import os
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional, Deque
from src.agents.observability import get_logger

try:
    from src.modules.send_telemetry_data import TelemetryDataSender
except ImportError:
    from modules.send_telemetry_data import TelemetryDataSender

logger = get_logger(__name__)


class ADXHandler(logging.Handler):
    """
    Python logging handler that ships logs to Azure Data Explorer.
    """

    def __init__(
        self,
        cluster_fqdn: str,
        database_name: str,
        table_name: str,
        client_id: str,
        batch_size: int = 100,
        flush_interval: float = 5.0,
        max_queue_size: int = 10000,
    ) -> None:
        """
        Initialize ADX handler.

        :param cluster_fqdn: ADX cluster FQDN (e.g., https://cluster.region.kusto.windows.net)
        :param database_name: ADX database name
        :param table_name: Table name for logs
        :param client_id: Managed identity client ID for authentication
        :param batch_size: Records to batch before sending
        :param flush_interval: Seconds between auto-flushes
        :param max_queue_size: Max queue size before dropping oldest
        """
        super().__init__()
        self.cluster_fqdn = cluster_fqdn
        self.database_name = database_name
        self.table_name = table_name
        self.client_id = client_id
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self._queue: Deque[dict[str, Any]] = deque(maxlen=max_queue_size)
        self._lock = threading.Lock()
        self._shutdown = threading.Event()
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()

    def send(
        self,
        data: dict[str, Any] | list[dict[str, Any]],
        table_name: Optional[str] = None,
    ) -> bool:
        """
        Send data to Azure Data Explorer in a single ingestion call.

        :param data: Single record or list of records to send
        :type data: dict | list[dict]
        :param table_name: Override table name for this call
        :type table_name: Optional[str]
        :returns: True if successful
        :rtype: bool
        """
        records = [data] if isinstance(data, dict) else data
        if not records:
            return True

        try:
            TelemetryDataSender(
                module_params={
                    "test_group_json_data": records[0] if len(records) == 1 else records,
                    "telemetry_data_destination": "azuredataexplorer",
                    "adx_cluster_fqdn": self.cluster_fqdn,
                    "adx_database_name": self.database_name,
                    "adx_client_id": self.client_id,
                    "telemetry_table_name": table_name or self.table_name,
                    "workspace_directory": "/tmp",
                }
            ).send_telemetry_data_to_azuredataexplorer(json.dumps(records))
            return True
        except Exception as e:
            logger.error(f"Failed to send to ADX: {e}")
            return False

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a log record to the queue."""
        try:
            log_entry = self._format_record(record)
            with self._lock:
                self._queue.append(log_entry)
                if len(self._queue) >= self.batch_size:
                    self._flush_queue()
        except Exception:
            self.handleError(record)

    def _format_record(self, record: logging.LogRecord) -> dict[str, Any]:
        """Format a log record as a dictionary."""
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info and self.formatter:
            entry["exception"] = self.formatter.formatException(record.exc_info)

        standard_attrs = {
            "name",
            "msg",
            "args",
            "created",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "exc_info",
            "exc_text",
            "thread",
            "threadName",
            "message",
            "asctime",
        }
        for key, value in record.__dict__.items():
            if key not in standard_attrs and not key.startswith("_"):
                if isinstance(value, (str, int, float, bool, type(None))):
                    entry[key] = value
                else:
                    try:
                        entry[key] = str(value)
                    except Exception:
                        pass

        return entry

    def _flush_queue(self) -> None:
        """Flush queued records (must hold lock)."""
        if not self._queue:
            return

        records = list(self._queue)
        self._queue.clear()

        threading.Thread(
            target=self._send_records,
            args=(records,),
            daemon=True,
        ).start()

    def _send_records(self, records: list[dict[str, Any]]) -> None:
        """Send records to ADX."""
        if self.send(records, self.table_name):
            logger.debug(f"Sent {len(records)} logs to ADX")

    def _flush_loop(self) -> None:
        """Background loop for periodic flushing."""
        while not self._shutdown.wait(self.flush_interval):
            with self._lock:
                self._flush_queue()

    def flush(self) -> None:
        """Flush all pending logs synchronously."""
        with self._lock:
            records = list(self._queue)
            self._queue.clear()

        if records:
            self.send(records, self.table_name)

    def close(self) -> None:
        """Close handler and flush remaining logs."""
        self._shutdown.set()
        self.flush()
        super().close()

    @classmethod
    def from_env(
        cls,
        table_name: Optional[str] = None,
        batch_size: int = 100,
        flush_interval: float = 5.0,
    ) -> Optional["ADXHandler"]:
        """
        Create handler from environment variables.

        :param table_name: Override table name
        :param batch_size: Records to batch before sending
        :param flush_interval: Seconds between auto-flushes
        :returns: ADXHandler if configured, None otherwise
        """
        cluster = os.environ.get("ADX_CLUSTER_FQDN")
        database = os.environ.get("ADX_DATABASE_NAME")
        table = table_name or os.environ.get("ADX_TABLE_NAME", "SAPQAServiceLogs")
        client_id = os.environ.get("ADX_CLIENT_ID")

        if not cluster or not database or not client_id:
            logger.info("ADX not configured - handler not created")
            return None

        logger.info(f"Creating ADX handler: cluster={cluster}, database={database}, table={table}")
        return cls(
            cluster_fqdn=cluster,
            database_name=database,
            table_name=table,
            client_id=client_id,
            batch_size=batch_size,
            flush_interval=flush_interval,
        )
