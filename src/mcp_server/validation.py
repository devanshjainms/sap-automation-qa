# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Input validation for MCP tool parameters.

``InputValidator`` holds shared state (workspace base path, session
registry, job store) so tool functions don't have to thread them
through every call.
"""

from __future__ import annotations

import re
from pathlib import Path
from mcp.server.fastmcp.exceptions import ToolError
from src.core.models.job import Job
from src.core.models.triage import TriageSession
from src.core.storage.job_store import JobStore

_WORKSPACE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MAX_QUERY_LENGTH = 500
MAX_WORKSPACE_ID_LENGTH = 128
MAX_DEFINITION_ID_LENGTH = 128
MAX_DEFINITIONS_COUNT = 50
MIN_TIMEOUT = 10
MAX_TIMEOUT = 300


class InputValidator:
    """Validates MCP tool inputs against domain rules.

    :param workspaces_base: Root directory containing workspace folders.
    :param sessions: Mutable dict of active triage sessions.
    :param job_store: Job persistence store (must have a ``.get()`` method).
    """

    def __init__(
        self,
        workspaces_base: Path,
        sessions: dict[str, TriageSession],
        job_store: JobStore,
    ) -> None:
        self._workspaces_base = workspaces_base
        self._sessions = sessions
        self._job_store = job_store

    def workspace_id(self, workspace_id: str) -> None:
        """Validate workspace ID format and existence.

        :param workspace_id: The workspace identifier to validate.
        :raises ToolError: If format is invalid or directory missing.
        """
        if not workspace_id:
            raise ToolError("workspace_id is required")

        if not _WORKSPACE_ID_RE.match(workspace_id):
            raise ToolError(
                f"Invalid workspace_id format: '{workspace_id}'. "
                "Must be alphanumeric with hyphens, underscores, or dots."
            )

        workspace_path = (self._workspaces_base / workspace_id).resolve()
        base_resolved = self._workspaces_base.resolve()
        if not str(workspace_path).startswith(str(base_resolved)):
            raise ToolError(f"Path traversal detected in workspace_id: '{workspace_id}'")

        if not workspace_path.is_dir():
            raise ToolError(f"Workspace '{workspace_id}' not found")

    def query(self, query: str) -> str:
        """Validate and sanitize a knowledge query string.

        :param query: The search query.
        :returns: Trimmed query string.
        :raises ToolError: If query is empty or too long.
        """
        query = query.strip()
        if not query:
            raise ToolError("query parameter is required")
        if len(query) > MAX_QUERY_LENGTH:
            raise ToolError(f"query exceeds maximum length ({MAX_QUERY_LENGTH} chars)")
        return query

    def timeout(self, timeout_seconds: int) -> int:
        """Validate timeout is within allowed range.

        :param timeout_seconds: Requested timeout.
        :returns: Validated timeout value.
        :raises ToolError: If timeout is outside bounds.
        """
        if timeout_seconds < MIN_TIMEOUT or timeout_seconds > MAX_TIMEOUT:
            raise ToolError(f"timeout_seconds must be between {MIN_TIMEOUT} and {MAX_TIMEOUT}")
        return timeout_seconds

    def definitions(self, definitions: list[str] | None) -> list[str] | None:
        """Validate evidence definition IDs.

        :param definitions: List of definition IDs, or None.
        :returns: Validated list or None.
        :raises ToolError: If list is too long or IDs are invalid.
        """
        if definitions is None:
            return None

        if len(definitions) > MAX_DEFINITIONS_COUNT:
            raise ToolError(f"Too many definitions (max {MAX_DEFINITIONS_COUNT})")

        for d in definitions:
            if not d or len(d) > MAX_DEFINITION_ID_LENGTH:
                raise ToolError(
                    f"Invalid definition ID: must be 1-{MAX_DEFINITION_ID_LENGTH} chars"
                )

        return definitions

    def session_id(self, session_id: str) -> TriageSession:
        """Validate session ID and return the session object.

        :param session_id: The session identifier.
        :returns: The triage session.
        :raises ToolError: If session_id is empty or not found.
        """
        if not session_id:
            raise ToolError("session_id is required")

        session = self._sessions.get(session_id)
        if session is None:
            raise ToolError(f"Session '{session_id}' not found")
        return session

    def job_id(self, job_id: str) -> Job:
        """Validate job ID and return the job object.

        :param job_id: The job identifier.
        :returns: The job model.
        :raises ToolError: If job_id is empty or not found.
        """
        if not job_id:
            raise ToolError("job_id is required")

        job = self._job_store.get(job_id)
        if job is None:
            raise ToolError(f"Job '{job_id}' not found")
        return job
