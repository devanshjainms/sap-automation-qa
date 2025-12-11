# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Base SQLite storage class for thread-safe database operations.

This module provides a common base class for SQLite-based storage
implementations, handling connection management, schema initialization,
and thread safety.
"""

import sqlite3
import threading
from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from src.agents.observability import get_logger

logger = get_logger(__name__)


class SQLiteBase(ABC):
    """Base class for SQLite storage implementations.

    Provides thread-safe connection management using connection-per-thread
    pattern. Subclasses must implement `_get_schema()` to define their
    table structure.

    :param db_path: Path to SQLite database file
    :type db_path: Path | str
    :param foreign_keys: Enable foreign key constraints (default: True)
    :type foreign_keys: bool
    """

    def __init__(self, db_path: Path | str, foreign_keys: bool = True) -> None:
        """Initialize SQLite storage.

        :param db_path: Path to SQLite database file
        :type db_path: Path | str
        :param foreign_keys: Enable foreign key constraints
        :type foreign_keys: bool
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._foreign_keys = foreign_keys
        self._local = threading.local()
        self._lock = threading.RLock()
        self._init_db()
        logger.info(f"{self.__class__.__name__} initialized at {self.db_path}")

    @abstractmethod
    def _get_schema(self) -> str:
        """Return the SQL schema for this storage.

        Subclasses must implement this to define their table structure.

        :returns: SQL schema string
        :rtype: str
        """
        pass

    def _init_db(self) -> None:
        """Initialize the database schema."""
        with self._get_connection() as conn:
            conn.executescript(self._get_schema())
            conn.commit()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a thread-local database connection.

        Creates a new connection for the current thread if one doesn't exist.

        :returns: SQLite connection for current thread
        :rtype: sqlite3.Connection
        """
        if not hasattr(self._local, "connection") or self._local.connection is None:
            self._local.connection = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            )
            self._local.connection.row_factory = sqlite3.Row
            if self._foreign_keys:
                self._local.connection.execute("PRAGMA foreign_keys = ON")
        return self._local.connection

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for database transactions.

        Provides automatic commit on success and rollback on failure.

        :yields: SQLite connection within transaction
        :rtype: Generator[sqlite3.Connection, None, None]
        """
        conn = self._get_connection()
        with self._lock:
            try:
                yield conn
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"Transaction failed: {e}")
                raise

    def execute(
        self,
        sql: str,
        params: tuple | dict | None = None,
        commit: bool = True,
    ) -> sqlite3.Cursor:
        """Execute a SQL statement.

        :param sql: SQL statement to execute
        :type sql: str
        :param params: Parameters for the SQL statement
        :type params: tuple | dict | None
        :param commit: Whether to commit the transaction
        :type commit: bool
        :returns: Cursor with results
        :rtype: sqlite3.Cursor
        """
        conn = self._get_connection()
        with self._lock:
            cursor = conn.execute(sql, params or ())
            if commit:
                conn.commit()
            return cursor

    def executemany(
        self,
        sql: str,
        params_list: list[tuple | dict],
        commit: bool = True,
    ) -> sqlite3.Cursor:
        """Execute a SQL statement with multiple parameter sets.

        :param sql: SQL statement to execute
        :type sql: str
        :param params_list: List of parameter sets
        :type params_list: list[tuple | dict]
        :param commit: Whether to commit the transaction
        :type commit: bool
        :returns: Cursor with results
        :rtype: sqlite3.Cursor
        """
        conn = self._get_connection()
        with self._lock:
            cursor = conn.executemany(sql, params_list)
            if commit:
                conn.commit()
            return cursor

    def fetchone(
        self,
        sql: str,
        params: tuple | dict | None = None,
    ) -> sqlite3.Row | None:
        """Execute a query and fetch one result.

        :param sql: SQL query
        :type sql: str
        :param params: Query parameters
        :type params: tuple | dict | None
        :returns: Single row or None
        :rtype: sqlite3.Row | None
        """
        cursor = self.execute(sql, params, commit=False)
        return cursor.fetchone()

    def fetchall(
        self,
        sql: str,
        params: tuple | dict | None = None,
    ) -> list[sqlite3.Row]:
        """Execute a query and fetch all results.

        :param sql: SQL query
        :type sql: str
        :param params: Query parameters
        :type params: tuple | dict | None
        :returns: List of rows
        :rtype: list[sqlite3.Row]
        """
        cursor = self.execute(sql, params, commit=False)
        return cursor.fetchall()

    def close(self) -> None:
        """Close the database connection for the current thread."""
        if hasattr(self._local, "connection") and self._local.connection:
            self._local.connection.close()
            self._local.connection = None
            logger.debug(f"{self.__class__.__name__} connection closed")

    def __enter__(self) -> "SQLiteBase":
        """Enter context manager."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context manager and close connection."""
        self.close()
