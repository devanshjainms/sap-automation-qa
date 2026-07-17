# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for workspace API routes backed by an injected reader."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from src.api.routes.workspaces import (
    _load_workspaces_from_directory,
    get_workspace_reader,
    set_workspace_backend,
)


class TestWorkspacesApi:
    """Verify workspace listing, lookup, validation, and dependency state."""

    def test_load_workspaces_uses_injected_backend(self, client: TestClient) -> None:
        """Return summaries supplied by the configured workspace reader."""
        workspaces = _load_workspaces_from_directory()

        assert {workspace.id for workspace in workspaces} >= {
            "NEW-WORKSPACE",
            "TEST-WORKSPACE-01",
        }

    def test_list_workspaces_endpoint(self, client: TestClient) -> None:
        """Return the workspace collection and total count."""
        response = client.get("/api/v1/workspaces")

        assert response.status_code == 200
        assert response.json()["total"] == len(response.json()["workspaces"])

    def test_get_existing_workspace(self, client: TestClient) -> None:
        """Return workspace details from the configured backend."""
        response = client.get("/api/v1/workspaces/TEST-WORKSPACE-01")

        assert response.status_code == 200
        assert response.json()["id"] == "TEST-WORKSPACE-01"

    def test_get_missing_workspace(self, client: TestClient) -> None:
        """Return not found when the backend cannot resolve a workspace."""
        response = client.get("/api/v1/workspaces/NONEXISTENT")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.parametrize(
        "workspace_id",
        ["..passwd", "..secret", "foo%5Cbar", "foo%00bar", "foo;bar", "%20"],
    )
    def test_rejects_invalid_workspace_ids(
        self,
        client: TestClient,
        workspace_id: str,
    ) -> None:
        """Reject unsafe workspace identifiers before backend access.

        :param client: FastAPI test client with an injected workspace backend.
        :param workspace_id: Encoded invalid identifier to request.
        """
        response = client.get(f"/api/v1/workspaces/{workspace_id}")

        assert response.status_code == 400

    @pytest.mark.parametrize("workspace_id", ["DEV-EUS2-SAP01", "ws.v2.test"])
    def test_accepts_valid_workspace_ids(
        self,
        client: TestClient,
        workspace_id: str,
    ) -> None:
        """Allow valid identifiers to reach the backend.

        :param client: FastAPI test client with an injected workspace backend.
        :param workspace_id: Valid identifier absent from the fake backend.
        """
        response = client.get(f"/api/v1/workspaces/{workspace_id}")

        assert response.status_code == 404

    def test_reader_requires_initialization(self) -> None:
        """Return service unavailable when no workspace reader is configured."""
        set_workspace_backend(None)

        with pytest.raises(HTTPException) as exc_info:
            get_workspace_reader()

        assert exc_info.value.status_code == 503
