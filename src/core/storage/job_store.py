# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""SQLite-based storage for jobs."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional
from uuid import UUID
from src.core.execution.exceptions import WorkspaceLockError
from src.core.models.job import Job, JobHistoryQuery, JobStatus
from src.core.observability import get_logger
from src.core.storage.staf_store import StafStore

logger = get_logger(__name__)

_JOBS_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    schedule_id  TEXT,
    test_group   TEXT,
    test_ids     TEXT NOT NULL DEFAULT '[]',
    status       TEXT NOT NULL DEFAULT 'pending',
    created_at   TEXT NOT NULL,
    started_at   TEXT,
    completed_at TEXT,
    error        TEXT,
    result       TEXT,
    log_file     TEXT,
    events       TEXT NOT NULL DEFAULT '[]',
    metadata     TEXT NOT NULL DEFAULT '{}',
    actor        TEXT,
    approval_ref TEXT,
    incident_ticket TEXT,
    offline      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS workspace_locks (
    workspace_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_jobs_workspace
    ON jobs(workspace_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status
    ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_schedule
    ON jobs(schedule_id);
CREATE INDEX IF NOT EXISTS idx_jobs_created
    ON jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_workspace_locks_job
    ON workspace_locks(job_id);
"""

_JOB_COLUMN_MIGRATIONS = {
    "actor": "ALTER TABLE jobs ADD COLUMN actor TEXT",
    "approval_ref": "ALTER TABLE jobs ADD COLUMN approval_ref TEXT",
    "incident_ticket": "ALTER TABLE jobs ADD COLUMN incident_ticket TEXT",
    "offline": "ALTER TABLE jobs ADD COLUMN offline INTEGER NOT NULL DEFAULT 0",
}


def _migrate_job_schema(db: StafStore) -> None:
    """Add columns introduced after the initial jobs schema.

    :param db: Shared SQLite connection owner.
    """
    with db.lock, db.conn:
        columns = {row[1] for row in db.conn.execute("PRAGMA table_info(jobs)").fetchall()}
        for column, statement in _JOB_COLUMN_MIGRATIONS.items():
            if column not in columns:
                db.conn.execute(statement)
        db.conn.execute("""
            CREATE TABLE IF NOT EXISTS workspace_locks (
                workspace_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
            )
            """)
        db.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_workspace_locks_job ON workspace_locks(job_id)"
        )
        db.conn.execute(
            """
            INSERT OR IGNORE INTO workspace_locks (workspace_id, job_id, created_at)
            SELECT workspace_id, id, created_at
            FROM jobs
            WHERE status NOT IN (?, ?, ?)
            """,
            (
                JobStatus.COMPLETED.value,
                JobStatus.FAILED.value,
                JobStatus.CANCELLED.value,
            ),
        )


def _dt_to_iso(dt: Optional[datetime]) -> Optional[str]:
    """Convert datetime to ISO-8601 string for SQLite storage.

    :param dt: Datetime to convert.
    :returns: ISO string or None.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class JobStore:
    """SQLite-backed storage for execution jobs.

    Uses WAL journal mode for crash safety and concurrent
    read performance. All writes are wrapped in transactions.
    """

    def __init__(
        self,
        db_path: Path | str = "data/scheduler.db",
        *,
        db: Optional[StafStore] = None,
    ) -> None:
        """Initialize the job store.

        :param db_path: Path to SQLite database file. Ignored when ``db`` is given.
        :param db: Optional shared ``StafStore`` connection owner. When omitted, the
            store creates and owns its own ``StafStore`` at ``db_path``.
        """
        if db is None:
            db = StafStore(db_path)
            self._owns_db = True
        else:
            self._owns_db = False
        self._db = db
        self._conn = db.conn
        self._lock = db.lock
        self.db_path = db.db_path
        db.executescript(_JOBS_SCHEMA)
        _migrate_job_schema(db)
        logger.info(f"Initialized job storage at {self.db_path}")

    def close(self) -> None:
        """Close the database connection if this store owns it."""
        if self._owns_db:
            self._db.close()

    @staticmethod
    def _job_to_row(job: Job) -> dict:
        """Convert a Job model to a flat dict for SQLite storage."""
        return {
            "id": str(job.id),
            "workspace_id": job.workspace_id,
            "schedule_id": job.schedule_id,
            "test_group": job.test_group,
            "test_ids": json.dumps(job.test_ids),
            "status": job.status if isinstance(job.status, str) else job.status.value,
            "created_at": _dt_to_iso(job.created_at),
            "started_at": _dt_to_iso(job.started_at),
            "completed_at": _dt_to_iso(job.completed_at),
            "error": job.error,
            "result": json.dumps(job.result, default=str) if job.result is not None else None,
            "log_file": job.log_file,
            "events": json.dumps(
                [e.model_dump(mode="json") for e in job.events],
                default=str,
            ),
            "metadata": json.dumps(job.metadata, default=str),
            "actor": job.actor,
            "approval_ref": job.approval_ref,
            "incident_ticket": job.incident_ticket,
            "offline": 1 if job.offline else 0,
        }

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Job:
        """Reconstruct a Job model from a database row."""
        data = dict(row)
        data["test_ids"] = json.loads(data["test_ids"])
        data["events"] = json.loads(data["events"])
        data["metadata"] = json.loads(data["metadata"])
        data["result"] = json.loads(data["result"]) if data["result"] else None
        for dt_field in ("created_at", "started_at", "completed_at"):
            if data.get(dt_field):
                data[dt_field] = datetime.fromisoformat(data[dt_field])
        data.setdefault("actor", None)
        data.setdefault("approval_ref", None)
        data.setdefault("incident_ticket", None)
        data["offline"] = bool(data.get("offline", 0))
        return Job.model_validate(data)

    def create(self, job: Job) -> Job:
        """Create a new job.

        :param job: Job to create.
        :returns: Created job.
        :raises WorkspaceLockError: If the workspace already has an active job.
        """
        row = self._job_to_row(job)
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO jobs
                   (id, workspace_id, schedule_id, test_group,
                    test_ids, status, created_at, started_at,
                    completed_at, error, result, log_file,
                    events, metadata,
                    actor, approval_ref, incident_ticket, offline)
                   VALUES
                   (:id, :workspace_id, :schedule_id, :test_group,
                    :test_ids, :status, :created_at, :started_at,
                    :completed_at, :error, :result, :log_file,
                    :events, :metadata,
                    :actor, :approval_ref, :incident_ticket, :offline)
                """,
                row,
            )
            if not job.is_terminal:
                try:
                    self._conn.execute(
                        """
                       INSERT INTO workspace_locks (workspace_id, job_id, created_at)
                       VALUES (?, ?, ?)
                       """,
                        (job.workspace_id, str(job.id), row["created_at"]),
                    )
                except sqlite3.IntegrityError as exc:
                    self._conn.execute("DELETE FROM jobs WHERE id = ?", (str(job.id),))
                    lock_row = self._conn.execute(
                        "SELECT job_id FROM workspace_locks WHERE workspace_id = ?",
                        (job.workspace_id,),
                    ).fetchone()
                    active_job_id = lock_row[0] if lock_row else "unknown"
                    raise WorkspaceLockError(
                        workspace_id=job.workspace_id,
                        active_job_id=active_job_id,
                    ) from exc
        logger.info(f"Created job {job.id} for workspace {job.workspace_id}")
        return job

    def get(self, job_id: UUID | str) -> Optional[Job]:
        """Get a job by ID.

        :param job_id: Job ID.
        :returns: Job if found, None otherwise.
        """
        with self._lock:
            self._conn.row_factory = sqlite3.Row
            row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (str(job_id),)).fetchone()
        return self._row_to_job(row) if row else None

    def update(self, job: Job) -> None:
        """Update an existing job.

        :param job: Job with updated fields.
        """
        row = self._job_to_row(job)
        with self._lock, self._conn:
            cur = self._conn.execute(
                """UPDATE jobs SET
                       workspace_id  = :workspace_id,
                       schedule_id   = :schedule_id,
                       test_group    = :test_group,
                       test_ids      = :test_ids,
                       status        = :status,
                       created_at    = :created_at,
                       started_at    = :started_at,
                       completed_at  = :completed_at,
                       error         = :error,
                       result        = :result,
                       log_file      = :log_file,
                       events        = :events,
                       metadata      = :metadata,
                       actor         = :actor,
                       approval_ref  = :approval_ref,
                       incident_ticket = :incident_ticket,
                       offline       = :offline
                   WHERE id = :id
                """,
                row,
            )
            if job.is_terminal:
                self._conn.execute(
                    "DELETE FROM workspace_locks WHERE workspace_id = ? AND job_id = ?",
                    (job.workspace_id, str(job.id)),
                )
        if cur.rowcount:
            logger.debug(f"Updated job {job.id} (status={job.status})")

    def get_active(self, workspace_id: Optional[str] = None) -> List[Job]:
        """Get active (non-terminal) jobs.

        :param workspace_id: Optional filter by workspace.
        :returns: List of active jobs.
        """
        terminal = (
            JobStatus.COMPLETED.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
        )
        with self._lock:
            self._conn.row_factory = sqlite3.Row
            if workspace_id:
                cur = self._conn.execute(
                    "SELECT * FROM jobs WHERE status NOT IN (?, ?, ?) AND workspace_id = ?",
                    (*terminal, workspace_id),
                )
            else:
                cur = self._conn.execute(
                    "SELECT * FROM jobs WHERE status NOT IN (?, ?, ?)",
                    terminal,
                )
            rows = cur.fetchall()
        return [self._row_to_job(r) for r in rows]

    def get_active_for_workspace(self, workspace_id: str) -> Optional[Job]:
        """Get the active job for a workspace.

        :param workspace_id: Workspace ID.
        :returns: Active job if one exists.
        """
        terminal = (
            JobStatus.COMPLETED.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
        )
        with self._lock:
            self._conn.row_factory = sqlite3.Row
            cur = self._conn.execute(
                "SELECT * FROM jobs "
                "WHERE workspace_id = ? "
                "AND status NOT IN (?, ?, ?) "
                "LIMIT 1",
                (workspace_id, *terminal),
            )
            row = cur.fetchone()
        return self._row_to_job(row) if row else None

    def has_active_job(self, workspace_id: str) -> bool:
        """Check if workspace has an active job.

        :param workspace_id: Workspace ID.
        :returns: True if active job exists.
        """
        return self.get_active_for_workspace(workspace_id) is not None

    def get_history(
        self,
        query: Optional[JobHistoryQuery] = None,
    ) -> List[Job]:
        """Get job history.

        :param query: Optional history filters and pagination.
        :returns: List of historical jobs.
        """
        query = query or JobHistoryQuery()
        terminal = (
            JobStatus.COMPLETED.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
        )

        clauses = [
            "status IN (?, ?, ?)",
            "created_at >= ?",
        ]
        params: list = [
            *terminal,
            _dt_to_iso(datetime.now(timezone.utc) - timedelta(days=query.days)),
        ]

        if query.workspace_id:
            clauses.append("workspace_id = ?")
            params.append(query.workspace_id)
        if query.schedule_id:
            clauses.append("schedule_id = ?")
            params.append(query.schedule_id)
        if query.status:
            status_val = query.status if isinstance(query.status, str) else query.status.value
            clauses.append("status = ?")
            params.append(status_val)

        where = " AND ".join(clauses)
        params.append(query.limit)

        with self._lock:
            self._conn.row_factory = sqlite3.Row
            cur = self._conn.execute(
                f"SELECT * FROM jobs WHERE {where} ORDER BY created_at DESC LIMIT ?",
                params,
            )
            rows = cur.fetchall()
        return [self._row_to_job(r) for r in rows]

    def get_jobs_for_schedule(
        self,
        schedule_id: str,
        limit: int = 50,
    ) -> List[Job]:
        """Get jobs triggered by a specific schedule.

        :param schedule_id: Schedule ID.
        :param limit: Maximum number of jobs.
        :returns: List of jobs.
        """
        return self.get_history(JobHistoryQuery(schedule_id=schedule_id, limit=limit))
