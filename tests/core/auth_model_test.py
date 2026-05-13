# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for AuthenticatedUser model."""

from src.core.models.auth import AuthenticatedUser


class TestAuthenticatedUser:
    """Tests for the AuthenticatedUser model."""

    def test_create_with_all_fields(self) -> None:
        user = AuthenticatedUser(
            oid="abc-123",
            name="Test User",
            email="test@example.com",
            tenant_id="tenant-001",
            roles=("admin", "reader"),
            raw_claims={"sub": "abc-123"},
        )
        assert user.oid == "abc-123"
        assert user.name == "Test User"
        assert user.email == "test@example.com"
        assert user.tenant_id == "tenant-001"
        assert len(user.roles) == 2
        assert user.raw_claims["sub"] == "abc-123"

    def test_is_frozen(self) -> None:
        user = AuthenticatedUser(
            oid="abc-123",
            name="Test",
            email="t@e.com",
            tenant_id="t1",
            roles=(),
            raw_claims={},
        )
        import dataclasses

        assert dataclasses.is_dataclass(user)
        with __import__("pytest").raises(dataclasses.FrozenInstanceError):
            user.name = "changed"
