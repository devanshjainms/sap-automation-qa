# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""SQLite-based job store for async execution tracking.

This module provides persistent storage for execution jobs,
enabling job status queries and history tracking.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional
from uuid import UUID

from src.agents.models.job import ExecutionJob, JobEvent, JobEventType, JobStatus
from src.agents.sqldb import SQLiteBase
from src.agents.observability import get_logger

logger = get_logger(__name__)

_JOB_SCHEMA = """
CREATE TABLE IF NOT EXISTS execution_jobs (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    user_id TEXT,
    workspace_id TEXT NOT NULL,
    test_id TEXT,
    test_group TEXT,
    test_ids TEXT DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending',
    progress_percent REAL DEFAULT 0.0,
    current_step TEXT,
    current_step_index INTEGER DEFAULT 0,
    total_steps INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    result TEXT,
    error_message TEXT,
    events TEXT DEFAULT '[]',
    metadata TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_jobs_conversation_id ON execution_jobs(conversation_id);
CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON execution_jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_jobs_workspace_id ON execution_jobs(workspace_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON execution_jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON execution_jobs(created_at);

CREATE TABLE IF NOT EXISTS job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    step_index INTEGER,
    total_steps INTEGER,
    progress_percent REAL,
    details TEXT,
    FOREIGN KEY (job_id) REFERENCES execution_jobs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_job_events_job_id ON job_events(job_id);
CREATE INDEX IF NOT EXISTS idx_job_events_timestamp ON job_events(timestamp);
"""


class JobStore(SQLiteBase):
    """SQLite-based storage for execution jobs.

    Extends SQLiteBase for thread-safe connection management.
    Supports event callbacks for real-time updates.
    """

    def __init__(self, db_path: Path | str = "data/jobs.db") -> None:
        """Initialize the job store.

        :param db_path: Path to SQLite database file
        :type db_path: Path | str
        """
        super().__init__(db_path, foreign_keys=True)
        self._event_callbacks: list[Callable[[str, JobEvent], None]] = []

    def _get_schema(self) -> str:
        """Return the SQL schema for job storage."""
        return _JOB_SCHEMA

    def register_event_callback(self, callback: Callable[[str, JobEvent], None]) -> None:
        """Register a callback to be called when job events occur.

        :param callback: Function taking (job_id, event) parameters
        :type callback: Callable[[str, JobEvent], None]
        """
        self._event_callbacks.append(callback)

    def _notify_event(self, job_id: str, event: JobEvent) -> None:
        """Notify all registered callbacks of a job event."""
        for callback in self._event_callbacks:
            try:
                callback(job_id, event)
            except Exception as e:
                logger.error(f"Error in event callback: {e}")

    def create_job(
        self,
        workspace_id: str,
        test_ids: list[str],
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        test_id: Optional[str] = None,
        test_group: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> ExecutionJob:
        """Create a new execution job.

        :param workspace_id: Target workspace for execution
        :type workspace_id: str
        :param test_ids: List of test IDs to execute
        :type test_ids: list[str]
        :param conversation_id: Associated conversation ID
        :type conversation_id: Optional[str]
        :param user_id: User who initiated the job
        :type user_id: Optional[str]
        :param test_id: Single test ID (if running one test)
        :type test_id: Optional[str]
        :param test_group: Test group (HA_DB_HANA, HA_SCS, etc.)
        :type test_group: Optional[str]
        :param metadata: Additional metadata
        :type metadata: Optional[dict[str, Any]]
        :returns: Created job
        :rtype: ExecutionJob
        """
        job = ExecutionJob(
            workspace_id=workspace_id,
            test_ids=test_ids,
            conversation_id=conversation_id,
            user_id=user_id,
            test_id=test_id,
            test_group=test_group,
            total_steps=len(test_ids),
            metadata=metadata or {},
        )

        self.execute(
            """
            INSERT INTO execution_jobs (
                id, conversation_id, user_id, workspace_id, test_id, test_group,
                test_ids, status, progress_percent, current_step, current_step_index,
                total_steps, created_at, started_at, completed_at, result,
                error_message, events, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(job.id),
                job.conversation_id,
                job.user_id,
                job.workspace_id,
                job.test_id,
                job.test_group,
                json.dumps(job.test_ids),
                job.status.value,
                job.progress_percent,
                job.current_step,
                job.current_step_index,
                job.total_steps,
                job.created_at.isoformat(),
                None,
                None,
                None,
                None,
                json.dumps([]),
                json.dumps(job.metadata),
            ),
        )

        logger.info(f"Created job {job.id} for workspace {workspace_id}")
        return job

    def get_job(self, job_id: UUID | str) -> Optional[ExecutionJob]:
        """Get a job by ID.

        :param job_id: Job identifier
        :type job_id: UUID | str
        :returns: Job if found
        :rtype: Optional[ExecutionJob]
        """
        row = self.fetchone(
            "SELECT * FROM execution_jobs WHERE id = ?",
            (str(job_id),),
        )
        return self._row_to_job(row) if row else None

    def get_jobs_for_conversation(
        self, conversation_id: str, limit: int = 10
    ) -> list[ExecutionJob]:
        """Get jobs associated with a conversation.

        :param conversation_id: Conversation ID
        :type conversation_id: str
        :param limit: Maximum jobs to return
        :type limit: int
        :returns: List of jobs
        :rtype: list[ExecutionJob]
        """
        rows = self.fetchall(
            """
            SELECT * FROM execution_jobs
            WHERE conversation_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (conversation_id, limit),
        )
        return [self._row_to_job(row) for row in rows]

    def get_active_jobs(self, user_id: Optional[str] = None) -> list[ExecutionJob]:
        """Get currently running jobs.

        :param user_id: Optional user ID to filter by
        :type user_id: Optional[str]
        :returns: List of active jobs
        :rtype: list[ExecutionJob]
        """
        if user_id:
            rows = self.fetchall(
                """
                SELECT * FROM execution_jobs
                WHERE status IN ('pending', 'running')
                AND user_id = ?
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
        else:
            rows = self.fetchall(
                """
                SELECT * FROM execution_jobs
                WHERE status IN ('pending', 'running')
                ORDER BY created_at DESC
                """
            )
        return [self._row_to_job(row) for row in rows]

    def has_active_job_for_workspace(self, workspace_id: str) -> bool:
        """Check if workspace has an active (pending/running) job.

        Used to enforce workspace-level job locking - only one job
        per workspace can run at a time.

        :param workspace_id: Workspace ID to check
        :type workspace_id: str
        :returns: True if workspace has an active job
        :rtype: bool
        """
        row = self.fetchone(
            """
            SELECT 1 FROM execution_jobs
            WHERE workspace_id = ?
            AND status IN ('pending', 'running')
            LIMIT 1
            """,
            (workspace_id,),
        )
        return row is not None

    def get_active_job_for_workspace(self, workspace_id: str) -> Optional[ExecutionJob]:
        """Get the active job for a workspace, if any.

        :param workspace_id: Workspace ID to check
        :type workspace_id: str
        :returns: Active job or None
        :rtype: Optional[ExecutionJob]
        """
        row = self.fetchone(
            """
            SELECT * FROM execution_jobs
            WHERE workspace_id = ?
            AND status IN ('pending', 'running')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (workspace_id,),
        )
        return self._row_to_job(row) if row else None

    def update_job(self, job: ExecutionJob) -> None:
        """Update a job in the database.

        :param job: Job to update
        :type job: ExecutionJob
        """
        self.execute(
            """
            UPDATE execution_jobs SET
                status = ?,
                progress_percent = ?,
                current_step = ?,
                current_step_index = ?,
                total_steps = ?,
                started_at = ?,
                completed_at = ?,
                result = ?,
                error_message = ?,
                events = ?,
                metadata = ?
            WHERE id = ?
            """,
            (
                job.status.value,
                job.progress_percent,
                job.current_step,
                job.current_step_index,
                job.total_steps,
                job.started_at.isoformat() if job.started_at else None,
                job.completed_at.isoformat() if job.completed_at else None,
                json.dumps(job.result) if job.result else None,
                job.error_message,
                json.dumps([e.to_dict() for e in job.events]),
                json.dumps(job.metadata),
                str(job.id),
            ),
        )

    def add_event(self, job_id: str, event: JobEvent) -> None:
        """Add an event to a job.

        Persists event both in the job's event list and in job_events table.

        :param job_id: Job ID
        :type job_id: str
        :param event: Event to add
        :type event: JobEvent
        """
        self.execute(
            """
            INSERT INTO job_events (
                job_id, event_type, message, timestamp, step_index,
                total_steps, progress_percent, details
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                event.event_type.value,
                event.message,
                event.timestamp.isoformat(),
                event.step_index,
                event.total_steps,
                event.progress_percent,
                json.dumps(event.details) if event.details else None,
            ),
        )
        self._notify_event(job_id, event)

    def _row_to_job(self, row: sqlite3.Row) -> ExecutionJob:
        """Convert a database row to an ExecutionJob."""
        data = {
            "id": row["id"],
            "conversation_id": row["conversation_id"],
            "user_id": row["user_id"],
            "workspace_id": row["workspace_id"],
            "test_id": row["test_id"],
            "test_group": row["test_group"],
            "test_ids": json.loads(row["test_ids"]) if row["test_ids"] else [],
            "status": row["status"],
            "progress_percent": row["progress_percent"],
            "current_step": row["current_step"],
            "current_step_index": row["current_step_index"],
            "total_steps": row["total_steps"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "result": json.loads(row["result"]) if row["result"] else None,
            "error_message": row["error_message"],
            "events": json.loads(row["events"]) if row["events"] else [],
            "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
        }
        return ExecutionJob.from_dict(data)

    def get_job_history(
        self,
        workspace_id: Optional[str] = None,
        user_id: Optional[str] = None,
        status: Optional[JobStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ExecutionJob]:
        """Query job history with optional filters.

        :param workspace_id: Filter by workspace
        :type workspace_id: Optional[str]
        :param user_id: Filter by user
        :type user_id: Optional[str]
        :param status: Filter by status
        :type status: Optional[JobStatus]
        :param limit: Maximum results
        :type limit: int
        :param offset: Results offset
        :type offset: int
        :returns: List of matching jobs
        :rtype: list[ExecutionJob]
        """
        conditions = []
        params: list[Any] = []

        if workspace_id:
            conditions.append("workspace_id = ?")
            params.append(workspace_id)
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if status:
            conditions.append("status = ?")
            params.append(status.value)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        params.extend([limit, offset])

        rows = self.fetchall(
            f"""
            SELECT * FROM execution_jobs
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params),
        )
        return [self._row_to_job(row) for row in rows]

    def get_recent_events(self, job_id: str, limit: int = 50) -> list[JobEvent]:
        """Get recent events for a job from the events table.

        :param job_id: Job ID
        :type job_id: str
        :param limit: Maximum events to return
        :type limit: int
        :returns: List of events
        :rtype: list[JobEvent]
        """
        rows = self.fetchall(
            """
            SELECT * FROM job_events
            WHERE job_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (job_id, limit),
        )
        return [
            JobEvent(
                event_type=JobEventType(row["event_type"]),
                message=row["message"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                step_index=row["step_index"],
                total_steps=row["total_steps"],
                progress_percent=row["progress_percent"],
                details=json.loads(row["details"]) if row["details"] else None,
            )
            for row in rows
        ]
