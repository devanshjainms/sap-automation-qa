# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Storage factory — selects Azure Table Storage or SQLite based on config.

When ``AZURE_TABLE_ENDPOINT`` is set, uses Azure Table Storage with
DefaultAzureCredential. Otherwise falls back to SQLite via StafStore.
"""

from __future__ import annotations
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def create_job_store(
    data_dir: Path,
    db_name: str = "staf.db",
) -> Any:
    """Create a job store (Azure Table or SQLite).

    :param data_dir: Directory for SQLite database (fallback).
    :param db_name: SQLite database filename.
    :returns: JobStore-compatible instance.
    """
    endpoint = os.environ.get("AZURE_TABLE_ENDPOINT", "").strip()
    if endpoint:
        from src.core.storage.azure_table import AzureTableJobStore

        table_name = os.environ.get("AZURE_TABLE_JOBS", "jobs")
        logger.info("Using Azure Table Storage for jobs: %s", endpoint)
        return AzureTableJobStore(endpoint=endpoint, table_name=table_name)

    from src.core.storage.staf_store import StafStore
    from src.core.storage.job_store import JobStore

    db = StafStore(data_dir / db_name)
    store = JobStore(db=db)
    db.sync()
    return store


def create_schedule_store(
    data_dir: Path,
    db_name: str = "staf.db",
    staf_db: Any = None,
) -> Any:
    """Create a schedule store (Azure Table or SQLite).

    :param data_dir: Directory for SQLite database (fallback).
    :param db_name: SQLite database filename.
    :param staf_db: Existing StafStore to share (SQLite only).
    :returns: ScheduleStore-compatible instance.
    """
    endpoint = os.environ.get("AZURE_TABLE_ENDPOINT", "").strip()
    if endpoint:
        from src.core.storage.azure_table import AzureTableScheduleStore

        table_name = os.environ.get("AZURE_TABLE_SCHEDULES", "schedules")
        logger.info("Using Azure Table Storage for schedules: %s", endpoint)
        return AzureTableScheduleStore(endpoint=endpoint, table_name=table_name)

    from src.core.storage.staf_store import StafStore
    from src.core.storage.schedule_store import ScheduleStore

    if staf_db is None:
        staf_db = StafStore(data_dir / db_name)
    store = ScheduleStore(db=staf_db)
    staf_db.sync()
    return store
