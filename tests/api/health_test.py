# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for Health API routes."""

from fastapi.testclient import TestClient
from src.api.routes.health import set_service_status


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    def test_health_check(self, client: TestClient) -> None:
        """
        Returns healthy status.
        """
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert "version" in data

    def test_health_check_includes_service_status(self, client: TestClient) -> None:
        """
        Returns service status values set by the application.
        """
        set_service_status("scheduler", True)
        response = client.get("/healthz")

        assert response.status_code == 200
        assert response.json()["services"]["scheduler"] is True

    def test_root_endpoint(self, client: TestClient) -> None:
        """
        Root endpoint returns service info.
        """
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "service" in data
        assert "version" in data
