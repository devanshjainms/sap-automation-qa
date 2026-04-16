# PRD Addendum: E2E Security Test Specifications

> **Author**: Ash (Security & Quality Analyst)
> **Version**: 1.0 | **Status**: Draft
> **Date**: 2025-07-14
> **Parent Document**: [PRD: End-to-End Testing & Release Pipeline](./PRD_E2E_TESTING.md)
> **Stakeholders**: Engineering Leadership, DevOps, Security, QA

---

## Table of Contents

- [1. Overview](#1-overview)
- [2. API Security Test Cases (Stage 3b)](#2-api-security-test-cases-stage-3b)
- [3. Container Runtime Security Checks](#3-container-runtime-security-checks)
- [4. CIB XML Sanitization Specification](#4-cib-xml-sanitization-specification)
- [5. Release Supply Chain Security](#5-release-supply-chain-security)
- [6. Self-Hosted Runner Hardening Checklist](#6-self-hosted-runner-hardening-checklist)

---

## 1. Overview

This addendum provides detailed security test specifications referenced by the main
[E2E Testing PRD](./PRD_E2E_TESTING.md). It covers five security domains that require
dedicated validation during E2E test execution:

| Domain | PRD Stage Reference | Run Frequency |
|--------|-------------------|---------------|
| API Security Tests | [Stage 3: API Smoke Tests](./PRD_E2E_TESTING.md#stage-3-api-smoke-tests-new) | Every PR |
| Container Runtime Security | [Stage 2: Container Integration](./PRD_E2E_TESTING.md#stage-2-container-integration-tests-new) | Every PR |
| CIB XML Sanitization | [Stage 4: Offline SAP Validation](./PRD_E2E_TESTING.md#stage-4-offline-sap-validation-new) | Every PR |
| Release Supply Chain | [Stage 6: Release Gate](./PRD_E2E_TESTING.md#stage-6-release-gate-new) | Release only |
| Runner Hardening | [§4.1 Management Server](./PRD_E2E_TESTING.md#41-management-server-staf-host) | Operational |

These tests integrate into the pipeline stages defined in the main PRD (§5) and extend
the security considerations outlined in §9.

---

## 2. API Security Test Cases (Stage 3b)

These tests supplement the functional API smoke tests (API-001 through API-021) defined
in the main PRD §5 Stage 3. They validate that security controls enforced by the STAF
API behave correctly under adversarial conditions.

**Prerequisites**: Running docker-compose stack with `AUTH_DEV_MODE=false` and a valid
Azure AD test app registration (or mock OIDC provider for CI).

**Runner**: GitHub-hosted (ubuntu-latest) for mock-OIDC variants; self-hosted for
real Azure AD tests (Tier 3b).

### 2.1 Test Case Summary

| ID | Category | Test Name | HTTP | Endpoint | Expected |
|----|----------|-----------|------|----------|----------|
| SEC-001 | Authentication | Reject unauthenticated request | GET | `/api/v1/jobs` | 401 |
| SEC-002 | Authentication | Reject expired JWT | GET | `/api/v1/jobs` | 401 |
| SEC-003 | Authentication | Reject tampered JWT signature | GET | `/api/v1/jobs` | 401 |
| SEC-004 | Authorization | Reject invalid audience claim | GET | `/api/v1/jobs` | 403 |
| SEC-005 | Authorization | Reject wrong issuer | GET | `/api/v1/jobs` | 401 |
| SEC-006 | Input Validation | Reject SQL injection in query param | GET | `/api/v1/jobs?workspace_id=...` | 422 or 200 (no leak) |
| SEC-007 | Input Validation | Reject path traversal in workspace ID | POST | `/api/v1/jobs` | 422 |
| SEC-008 | Input Validation | Reject oversized request body | POST | `/api/v1/jobs` | 413 or 422 |
| SEC-009 | Rate Limiting | Enforce rate limit on job creation | POST | `/api/v1/jobs` | 429 |
| SEC-010 | CORS | Reject disallowed origin | OPTIONS | `/api/v1/jobs` | No `Access-Control-Allow-Origin` |

### 2.2 Detailed Specifications

---

#### SEC-001: Reject Unauthenticated Request

**Category**: Authentication
**Objective**: Verify the API rejects requests with no `Authorization` header when
`AUTH_DEV_MODE=false`.

| Field | Value |
|-------|-------|
| Method | `GET` |
| Endpoint | `/api/v1/jobs` |
| Headers | _(none — no Authorization header)_ |
| Payload | N/A |
| Expected Status | `401 Unauthorized` |
| Expected Body | `{"detail": "..."}` containing authentication error |

**Cross-reference**: Main PRD §9.1 (Credential Management), §4.4 (Azure AD app registration)

```python
# tests/e2e/test_api_security.py
import httpx
import pytest

BASE_URL = "http://localhost:8000"
API = f"{BASE_URL}/api/v1"


class TestAuthentication:
    """SEC-001 through SEC-003: Authentication enforcement."""

    def test_sec_001_reject_unauthenticated(self):
        """Requests without Authorization header must be rejected."""
        with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
            response = client.get(f"{API}/jobs")
            assert response.status_code == 401, (
                f"Expected 401 for unauthenticated request, got {response.status_code}"
            )
            body = response.json()
            assert "detail" in body
```

---

#### SEC-002: Reject Expired JWT

**Category**: Authentication
**Objective**: Verify the API rejects JWTs whose `exp` claim is in the past.

| Field | Value |
|-------|-------|
| Method | `GET` |
| Endpoint | `/api/v1/jobs` |
| Headers | `Authorization: Bearer <expired-jwt>` |
| Payload | N/A |
| Expected Status | `401 Unauthorized` |
| Expected Body | Error detail referencing token expiration |

```python
import time
import jwt  # PyJWT


def _make_expired_jwt(secret: str = "test-secret") -> str:
    """Create a JWT that expired 1 hour ago."""
    return jwt.encode(
        {
            "sub": "e2e-test-user",
            "aud": "staf-api",
            "iss": "https://login.microsoftonline.com/test-tenant/v2.0",
            "exp": int(time.time()) - 3600,
            "iat": int(time.time()) - 7200,
        },
        secret,
        algorithm="HS256",
    )


class TestExpiredToken:
    def test_sec_002_reject_expired_jwt(self):
        """Expired JWTs must be rejected with 401."""
        token = _make_expired_jwt()
        with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
            response = client.get(
                f"{API}/jobs",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 401
```

---

#### SEC-003: Reject Tampered JWT Signature

**Category**: Authentication
**Objective**: Verify the API rejects JWTs signed with an unknown key.

| Field | Value |
|-------|-------|
| Method | `GET` |
| Endpoint | `/api/v1/jobs` |
| Headers | `Authorization: Bearer <tampered-jwt>` |
| Payload | N/A |
| Expected Status | `401 Unauthorized` |
| Expected Body | Error detail referencing signature verification |

```python
class TestTamperedToken:
    def test_sec_003_reject_tampered_signature(self):
        """JWTs signed with the wrong key must be rejected."""
        token = jwt.encode(
            {
                "sub": "attacker",
                "aud": "staf-api",
                "iss": "https://login.microsoftonline.com/test-tenant/v2.0",
                "exp": int(time.time()) + 3600,
            },
            "wrong-secret-key",
            algorithm="HS256",
        )
        with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
            response = client.get(
                f"{API}/jobs",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 401
```

---

#### SEC-004: Reject Invalid Audience Claim

**Category**: Authorization
**Objective**: Verify the API rejects JWTs with an `aud` claim that does not match the
configured STAF API audience.

| Field | Value |
|-------|-------|
| Method | `GET` |
| Endpoint | `/api/v1/jobs` |
| Headers | `Authorization: Bearer <wrong-aud-jwt>` |
| Payload | N/A |
| Expected Status | `403 Forbidden` |
| Expected Body | Error detail referencing audience validation |

```python
class TestAuthorization:
    def test_sec_004_reject_invalid_audience(self):
        """JWTs with wrong audience claim must be rejected."""
        token = jwt.encode(
            {
                "sub": "e2e-test-user",
                "aud": "some-other-api",  # Wrong audience
                "iss": "https://login.microsoftonline.com/test-tenant/v2.0",
                "exp": int(time.time()) + 3600,
            },
            "test-secret",
            algorithm="HS256",
        )
        with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
            response = client.get(
                f"{API}/jobs",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code in (401, 403)
```

---

#### SEC-005: Reject Wrong Issuer

**Category**: Authorization
**Objective**: Verify the API rejects JWTs from an untrusted issuer (`iss` claim).

| Field | Value |
|-------|-------|
| Method | `GET` |
| Endpoint | `/api/v1/jobs` |
| Headers | `Authorization: Bearer <wrong-iss-jwt>` |
| Payload | N/A |
| Expected Status | `401 Unauthorized` |
| Expected Body | Error detail referencing issuer validation |

```python
    def test_sec_005_reject_wrong_issuer(self):
        """JWTs from an untrusted issuer must be rejected."""
        token = jwt.encode(
            {
                "sub": "e2e-test-user",
                "aud": "staf-api",
                "iss": "https://evil-issuer.example.com/v2.0",
                "exp": int(time.time()) + 3600,
            },
            "test-secret",
            algorithm="HS256",
        )
        with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
            response = client.get(
                f"{API}/jobs",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 401
```

---

#### SEC-006: Reject SQL Injection in Query Parameters

**Category**: Input Validation
**Objective**: Verify that SQL injection payloads in query parameters do not leak data
or cause errors. The STAF API uses Pydantic models and parameterized SQLite queries
(see `src/core/storage/`), so injections should be harmless.

| Field | Value |
|-------|-------|
| Method | `GET` |
| Endpoint | `/api/v1/jobs?workspace_id=' OR 1=1 --` |
| Headers | Valid auth token |
| Payload | N/A |
| Expected Status | `422 Unprocessable Entity` or `200` with empty results |
| Validation | Response must **not** contain data from other workspaces |

```python
class TestInputValidation:
    def test_sec_006_sql_injection_in_query_param(self, auth_headers: dict):
        """SQL injection in query params must not leak data."""
        payloads = [
            "' OR 1=1 --",
            "'; DROP TABLE jobs; --",
            "\" OR \"\"=\"",
            "1; SELECT * FROM sqlite_master",
        ]
        with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
            for payload in payloads:
                response = client.get(
                    f"{API}/jobs",
                    params={"workspace_id": payload},
                    headers=auth_headers,
                )
                assert response.status_code in (200, 422), (
                    f"Unexpected status {response.status_code} for payload: {payload}"
                )
                if response.status_code == 200:
                    data = response.json()
                    # Must not return jobs from other workspaces
                    for job in data.get("items", []):
                        assert job["workspace_id"] == payload or data["total"] == 0
```

---

#### SEC-007: Reject Path Traversal in Workspace ID

**Category**: Input Validation
**Objective**: Verify the API rejects workspace IDs containing path traversal sequences.
Workspace IDs map to filesystem paths under `WORKSPACES/SYSTEM/`, so traversal could
allow reading arbitrary files.

| Field | Value |
|-------|-------|
| Method | `POST` |
| Endpoint | `/api/v1/jobs` |
| Headers | Valid auth token, `Content-Type: application/json` |
| Payload | `{"workspace_id": "../../etc/passwd", "test_group": "ConfigurationChecks"}` |
| Expected Status | `422 Unprocessable Entity` |
| Expected Body | Validation error for `workspace_id` |

```python
    def test_sec_007_path_traversal_in_workspace_id(self, auth_headers: dict):
        """Path traversal in workspace_id must be rejected."""
        traversal_payloads = [
            "../../etc/passwd",
            "..\\..\\windows\\system32",
            "E2E-SMOKE/../../../etc/shadow",
            "E2E-SMOKE/./../../secrets",
            "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        ]
        with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
            for payload in traversal_payloads:
                response = client.post(
                    f"{API}/jobs",
                    json={
                        "workspace_id": payload,
                        "test_group": "ConfigurationChecks",
                    },
                    headers=auth_headers,
                )
                assert response.status_code in (400, 404, 422), (
                    f"Expected rejection for traversal payload '{payload}', "
                    f"got {response.status_code}"
                )
```

---

#### SEC-008: Reject Oversized Request Body

**Category**: Input Validation
**Objective**: Verify the API enforces a maximum request body size to prevent
denial-of-service via memory exhaustion.

| Field | Value |
|-------|-------|
| Method | `POST` |
| Endpoint | `/api/v1/jobs` |
| Headers | Valid auth token, `Content-Type: application/json` |
| Payload | 10 MB JSON body (`{"workspace_id": "A" * 10_000_000, ...}`) |
| Expected Status | `413 Request Entity Too Large` or `422 Unprocessable Entity` |

```python
    def test_sec_008_reject_oversized_body(self, auth_headers: dict):
        """Oversized request bodies must be rejected."""
        oversized_payload = {
            "workspace_id": "A" * 10_000_000,  # ~10 MB string
            "test_group": "ConfigurationChecks",
        }
        with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
            response = client.post(
                f"{API}/jobs",
                json=oversized_payload,
                headers=auth_headers,
            )
            assert response.status_code in (413, 422), (
                f"Expected 413 or 422 for oversized body, got {response.status_code}"
            )
```

---

#### SEC-009: Enforce Rate Limit on Job Creation

**Category**: Rate Limiting
**Objective**: Verify the API enforces rate limiting on job creation to prevent abuse.
The STAF workspace locking mechanism (one active job per workspace) provides implicit
rate limiting, but explicit rate limiting should also be present.

| Field | Value |
|-------|-------|
| Method | `POST` |
| Endpoint | `/api/v1/jobs` |
| Headers | Valid auth token |
| Payload | Valid job creation body, repeated rapidly |
| Expected Status | `429 Too Many Requests` after threshold |

```python
    def test_sec_009_rate_limit_job_creation(self, auth_headers: dict):
        """Rapid job creation must eventually be rate-limited."""
        with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
            statuses = []
            for i in range(50):
                response = client.post(
                    f"{API}/jobs",
                    json={
                        "workspace_id": f"RATE-LIMIT-TEST-{i}",
                        "test_group": "ConfigurationChecks",
                    },
                    headers=auth_headers,
                )
                statuses.append(response.status_code)
                if response.status_code == 429:
                    break

            # At least one request should have been rate-limited,
            # OR workspace lock (409) kicks in as an implicit limit
            rate_limited = any(s in (429, 409) for s in statuses)
            assert rate_limited, (
                f"No rate limiting detected after {len(statuses)} requests. "
                f"Statuses: {set(statuses)}"
            )
```

---

#### SEC-010: Reject Disallowed CORS Origin

**Category**: CORS
**Objective**: Verify the API does not include `Access-Control-Allow-Origin` for
origins not listed in the `CORS_ORIGINS` environment variable (see `src/api/app.py`).

| Field | Value |
|-------|-------|
| Method | `OPTIONS` |
| Endpoint | `/api/v1/jobs` |
| Headers | `Origin: https://evil-site.example.com` |
| Payload | N/A |
| Expected Status | `200` or `400` |
| Validation | Response must **not** contain `Access-Control-Allow-Origin: https://evil-site.example.com` |

**Cross-reference**: `CORS_ORIGINS` configuration in `src/api/app.py` and `deploy/.env.example`

```python
class TestCORS:
    def test_sec_010_reject_disallowed_origin(self):
        """Disallowed CORS origins must not receive Access-Control-Allow-Origin."""
        with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
            response = client.options(
                f"{API}/jobs",
                headers={
                    "Origin": "https://evil-site.example.com",
                    "Access-Control-Request-Method": "GET",
                },
            )
            allow_origin = response.headers.get("access-control-allow-origin", "")
            assert allow_origin != "https://evil-site.example.com", (
                "CORS allowed a disallowed origin"
            )
            assert allow_origin != "*", (
                "CORS wildcard (*) is not acceptable in production"
            )
```

### 2.3 Test Fixtures & Helpers

```python
# tests/e2e/conftest.py (security test additions)
import os
import pytest


@pytest.fixture(scope="session")
def auth_headers() -> dict:
    """Provide valid authentication headers for security tests.

    In CI, this uses a test Azure AD app registration or mock OIDC token.
    Set STAF_E2E_AUTH_TOKEN to provide a pre-generated token.
    """
    token = os.environ.get("STAF_E2E_AUTH_TOKEN")
    if not token:
        pytest.skip("STAF_E2E_AUTH_TOKEN not set; skipping authenticated security tests")
    return {"Authorization": f"Bearer {token}"}
```

---

## 3. Container Runtime Security Checks

These checks extend the Container Integration tests (CI-001 through CI-013) defined
in the main PRD §5 Stage 2. They verify that the Docker container follows security
best practices established in `deploy/Dockerfile`.

**Cross-reference**: Main PRD [Stage 2: Container Integration](./PRD_E2E_TESTING.md#stage-2-container-integration-tests-new),
Dockerfile at `deploy/Dockerfile` (non-root user `appuser:1000`).

### 3.1 Test Cases

| ID | Check | Command / Method | Pass Criteria |
|----|-------|-----------------|---------------|
| CRT-001 | Non-root user | `docker exec ... id -u` | UID ≠ 0 (expect 1000) |
| CRT-002 | No excessive capabilities | `docker inspect --format='{{.HostConfig.CapAdd}}'` | Empty or `[]` |
| CRT-003 | No secrets in env vars | `docker inspect --format='{{.Config.Env}}'` | No `PASSWORD`, `SECRET`, `KEY`, `TOKEN` values |
| CRT-004 | Read-only root filesystem | `docker inspect --format='{{.HostConfig.ReadonlyRootfs}}'` | `true` (or documented exception) |
| CRT-005 | No privileged mode | `docker inspect --format='{{.HostConfig.Privileged}}'` | `false` |
| CRT-006 | Health check defined | `docker inspect --format='{{.Config.Healthcheck}}'` | Non-empty health check command |
| CRT-007 | No host network | `docker inspect --format='{{.HostConfig.NetworkMode}}'` | Not `host` |
| CRT-008 | Dropped capabilities | `docker inspect --format='{{.HostConfig.CapDrop}}'` | Contains `ALL` or specific dangerous caps |

### 3.2 Implementation

```bash
#!/usr/bin/env bash
# tests/e2e/test_container_security.sh
# Container runtime security validation
# Extends CI-001..CI-013 from the main PRD Stage 2
set -euo pipefail

CONTAINER_NAME="sap-qa-service"
FAILURES=0

log()  { echo "[$(date -u +%H:%M:%S)] $*"; }
pass() { log "PASS: $1"; }
fail() { log "FAIL: $1"; ((FAILURES++)); }

# CRT-001: Verify non-root user
log "CRT-001: Checking container runs as non-root..."
UID_VAL=$(docker exec "$CONTAINER_NAME" id -u 2>/dev/null || echo "error")
if [ "$UID_VAL" = "0" ]; then
    fail "CRT-001 — container running as root (UID=0)"
elif [ "$UID_VAL" = "1000" ]; then
    pass "CRT-001 — running as UID $UID_VAL (appuser)"
else
    pass "CRT-001 — running as non-root UID $UID_VAL"
fi

# CRT-002: No excessive capabilities
log "CRT-002: Checking capabilities..."
CAP_ADD=$(docker inspect --format='{{.HostConfig.CapAdd}}' "$CONTAINER_NAME" 2>/dev/null)
if [ "$CAP_ADD" = "[]" ] || [ "$CAP_ADD" = "<nil>" ] || [ -z "$CAP_ADD" ]; then
    pass "CRT-002 — no added capabilities"
else
    fail "CRT-002 — capabilities added: $CAP_ADD"
fi

# CRT-003: No secrets in environment variables
log "CRT-003: Checking for secrets in environment..."
ENV_VARS=$(docker inspect --format='{{range .Config.Env}}{{println .}}{{end}}' "$CONTAINER_NAME")
SECRET_PATTERNS=("PASSWORD=" "SECRET=" "PRIVATE_KEY=" "API_KEY=" "ACCESS_TOKEN=")
FOUND_SECRET=false
for pattern in "${SECRET_PATTERNS[@]}"; do
    if echo "$ENV_VARS" | grep -qi "$pattern"; then
        # Allow known safe patterns (e.g., AUTH_DEV_MODE, LOG_LEVEL)
        MATCH=$(echo "$ENV_VARS" | grep -i "$pattern" | head -1)
        fail "CRT-003 — potential secret in env: $MATCH"
        FOUND_SECRET=true
    fi
done
if [ "$FOUND_SECRET" = false ]; then
    pass "CRT-003 — no secrets detected in environment variables"
fi

# CRT-004: Read-only root filesystem
log "CRT-004: Checking read-only root filesystem..."
READONLY=$(docker inspect --format='{{.HostConfig.ReadonlyRootfs}}' "$CONTAINER_NAME" 2>/dev/null)
if [ "$READONLY" = "true" ]; then
    pass "CRT-004 — read-only root filesystem enabled"
else
    log "WARN: CRT-004 — read-only root filesystem is not enabled (ReadonlyRootfs=$READONLY)"
    log "  NOTE: This may be acceptable if tmpfs mounts are used for writable paths."
    log "  Verify that writable paths are limited to: /app/data, /app/WORKSPACES, /tmp"
fi

# CRT-005: No privileged mode
log "CRT-005: Checking privileged mode..."
PRIVILEGED=$(docker inspect --format='{{.HostConfig.Privileged}}' "$CONTAINER_NAME" 2>/dev/null)
if [ "$PRIVILEGED" = "false" ]; then
    pass "CRT-005 — not running in privileged mode"
else
    fail "CRT-005 — container is running in PRIVILEGED mode"
fi

# CRT-006: Health check defined
log "CRT-006: Checking health check..."
HEALTHCHECK=$(docker inspect --format='{{.Config.Healthcheck}}' "$CONTAINER_NAME" 2>/dev/null)
if [ -n "$HEALTHCHECK" ] && [ "$HEALTHCHECK" != "<nil>" ]; then
    pass "CRT-006 — health check is defined"
else
    fail "CRT-006 — no health check defined in container"
fi

# CRT-007: No host networking
log "CRT-007: Checking network mode..."
NETMODE=$(docker inspect --format='{{.HostConfig.NetworkMode}}' "$CONTAINER_NAME" 2>/dev/null)
if [ "$NETMODE" = "host" ]; then
    fail "CRT-007 — container using host network mode"
else
    pass "CRT-007 — network mode: $NETMODE (not host)"
fi

# CRT-008: Dropped capabilities
log "CRT-008: Checking dropped capabilities..."
CAP_DROP=$(docker inspect --format='{{.HostConfig.CapDrop}}' "$CONTAINER_NAME" 2>/dev/null)
if echo "$CAP_DROP" | grep -qi "all"; then
    pass "CRT-008 — all capabilities dropped"
else
    log "WARN: CRT-008 — CapDrop=$CAP_DROP (consider dropping ALL and adding back only needed caps)"
fi

log "Container security checks: $FAILURES failures"
exit "$FAILURES"
```

### 3.3 Docker-Compose Hardening Recommendations

To pass all CRT checks, the `deploy/docker-compose.yml` should include:

```yaml
services:
  sap-qa-service:
    # ... existing config ...
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    read_only: true
    tmpfs:
      - /tmp:noexec,nosuid,size=100m
      - /app/.cache:noexec,nosuid,size=50m
    volumes:
      - staf-data:/app/data        # Writable: SQLite DB
      - ./WORKSPACES:/app/WORKSPACES  # Writable: workspace data
```

---

## 4. CIB XML Sanitization Specification

CIB (Cluster Information Base) XML files captured from live Pacemaker clusters for
offline validation (see main PRD [Stage 4](./PRD_E2E_TESTING.md#stage-4-offline-sap-validation-new))
may contain sensitive data. This specification defines what must be stripped before
CIB fixtures are committed to the repository.

**Cross-reference**: Offline validation fixtures stored in
`WORKSPACES/SYSTEM/{ID}/offline_validation/cib.xml`, consumed by
`src/modules/get_pcmk_properties_db.py` and `src/modules/get_pcmk_properties_scs.py`.

### 4.1 Sensitive Fields to Strip

| Category | XPath Pattern | Example Content | Action |
|----------|-------------|-----------------|--------|
| STONITH passwords | `//nvpair[@name='passwd']` | Fencing agent credentials | Replace value with `REDACTED` |
| STONITH pcmk_host_map | `//nvpair[@name='pcmk_host_map']` | Host-to-port mappings with IPs | Replace IPs with `10.0.0.x` |
| SBD device paths | `//nvpair[@name='SBD_DEVICE']` | `/dev/disk/by-id/scsi-...` | Replace with `/dev/disk/by-id/scsi-REDACTED` |
| Azure fence agent login | `//nvpair[@name='login']` | Azure AD app ID | Replace with `00000000-0000-0000-0000-000000000000` |
| Azure fence agent passwd | `//nvpair[@name='passwd']` | Azure AD app secret | Replace with `REDACTED` |
| IP addresses in resources | `//nvpair[@name='ip']` | VIP addresses `10.x.x.x` | Replace with `10.0.0.100` |
| Monitoring secrets | `//nvpair[contains(@name, 'secret')]` | Various secrets | Replace with `REDACTED` |
| SSH keys | `//nvpair[contains(@name, 'ssh')]` | SSH key paths or values | Replace with `REDACTED` |
| Custom HANA passwords | `//nvpair[contains(@name, 'password')]` | HANA system DB passwords | Replace with `REDACTED` |
| Subscription IDs | `//nvpair[@name='subscriptionId']` | Azure subscription GUID | Replace with `00000000-0000-0000-0000-000000000000` |
| Resource group names | `//nvpair[@name='resourceGroup']` | Actual RG names | Replace with `rg-e2e-sanitized` |
| Tenant IDs | `//nvpair[@name='tenantId']` | Azure tenant GUID | Replace with `00000000-0000-0000-0000-000000000000` |

### 4.2 XPath Patterns for Sensitive Data

```xpath
<!-- Passwords and secrets (case-insensitive match on name) -->
//nvpair[
    contains(translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'passwd')
    or contains(translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'password')
    or contains(translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'secret')
]

<!-- Azure identity fields -->
//nvpair[@name='login' or @name='subscriptionId' or @name='tenantId' or @name='resourceGroup']

<!-- STONITH device configuration -->
//primitive[@type='fence_azure_arm']//nvpair
//primitive[@type='external/sbd']//nvpair[@name='SBD_DEVICE']

<!-- IP addresses in resource configuration -->
//primitive[@type='IPaddr2']//nvpair[@name='ip']
```

### 4.3 Python Sanitization Function

```python
"""
CIB XML sanitization for offline test fixtures.

Strips sensitive data from Pacemaker CIB XML while preserving structure
required by offline validation modules:
  - src/modules/get_pcmk_properties_db.py
  - src/modules/get_pcmk_properties_scs.py
  - src/module_utils/get_pcmk_properties.py (BaseHAClusterValidator)
"""

import re
from copy import deepcopy
from lxml import etree


# Patterns matching sensitive nvpair @name attributes
_SENSITIVE_NAME_PATTERNS: list[re.Pattern] = [
    re.compile(r"passwd", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"^login$", re.IGNORECASE),
    re.compile(r"ssh", re.IGNORECASE),
]

# Names requiring GUID replacement
_GUID_NAMES: set[str] = {"subscriptionId", "tenantId", "login"}
_REDACTED_GUID: str = "00000000-0000-0000-0000-000000000000"

# Names requiring generic replacement
_GENERIC_REPLACE: dict[str, str] = {
    "resourceGroup": "rg-e2e-sanitized",
    "SBD_DEVICE": "/dev/disk/by-id/scsi-REDACTED",
}

# IP address regex for value replacement
_IP_PATTERN: re.Pattern = re.compile(
    r"\b(?:10|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}\b"
)


def sanitize_cib_xml(cib_xml: str) -> str:
    """Sanitize a CIB XML string by redacting sensitive values.

    Args:
        cib_xml: Raw CIB XML string from ``cibadmin --query``.

    Returns:
        Sanitized XML string with sensitive values replaced.

    Raises:
        etree.XMLSyntaxError: If the input is not valid XML.
    """
    tree = etree.fromstring(cib_xml.encode("utf-8"))
    sanitized = deepcopy(tree)

    for nvpair in sanitized.iter("nvpair"):
        name = nvpair.get("name", "")
        value = nvpair.get("value", "")

        # Check sensitive name patterns
        for pattern in _SENSITIVE_NAME_PATTERNS:
            if pattern.search(name):
                nvpair.set("value", "REDACTED")
                break

        # GUID fields
        if name in _GUID_NAMES:
            nvpair.set("value", _REDACTED_GUID)

        # Generic replacements
        if name in _GENERIC_REPLACE:
            nvpair.set("value", _GENERIC_REPLACE[name])

        # Sanitize private IP addresses in any remaining values
        if _IP_PATTERN.search(value) and name == "ip":
            nvpair.set("value", "10.0.0.100")
        elif _IP_PATTERN.search(value) and name == "pcmk_host_map":
            nvpair.set("value", _IP_PATTERN.sub("10.0.0.1", value))

    return etree.tostring(sanitized, pretty_print=True, xml_declaration=True, encoding="UTF-8").decode("utf-8")


def validate_sanitized_cib(sanitized_xml: str) -> bool:
    """Validate that sanitized CIB XML is still parseable.

    Ensures the sanitization did not break the XML structure required
    by the offline validation modules.

    Args:
        sanitized_xml: Sanitized CIB XML string.

    Returns:
        True if the XML is valid and contains expected elements.

    Raises:
        ValueError: If required CIB elements are missing.
    """
    tree = etree.fromstring(sanitized_xml.encode("utf-8"))

    # Verify core CIB structure is intact
    required_sections = ["configuration", "status"]
    for section in required_sections:
        if tree.find(f".//{section}") is None:
            raise ValueError(f"Required CIB section '{section}' missing after sanitization")

    # Verify resources section exists (needed by offline tests)
    resources = tree.find(".//resources")
    if resources is None:
        raise ValueError("CIB 'resources' section missing after sanitization")

    # Verify no plaintext secrets remain
    for nvpair in tree.iter("nvpair"):
        name = nvpair.get("name", "").lower()
        value = nvpair.get("value", "")
        if any(p.search(name) for p in _SENSITIVE_NAME_PATTERNS):
            if value not in ("REDACTED", _REDACTED_GUID, ""):
                raise ValueError(
                    f"Sensitive field '{nvpair.get('name')}' still contains "
                    f"non-redacted value after sanitization"
                )

    return True
```

### 4.4 Usage in E2E Pipeline

```bash
# Sanitize a captured CIB before committing to fixtures
python3 -c "
from tests.e2e.cib_sanitizer import sanitize_cib_xml, validate_sanitized_cib
import sys

raw_cib = sys.stdin.read()
sanitized = sanitize_cib_xml(raw_cib)
validate_sanitized_cib(sanitized)
print(sanitized)
" < captured_cib.xml > WORKSPACES/SYSTEM/E2E-OFFLINE-SUSE/offline_validation/cib.xml
```

### 4.5 Validation Test

```python
# tests/e2e/test_cib_sanitization.py
"""Verify CIB sanitization preserves structure for offline tests."""

import pytest
from pathlib import Path


CIB_FIXTURE_DIRS = [
    "WORKSPACES/SYSTEM/E2E-OFFLINE-SUSE/offline_validation",
    "WORKSPACES/SYSTEM/E2E-OFFLINE-RHEL/offline_validation",
]


class TestCIBSanitization:
    @pytest.mark.parametrize("fixture_dir", CIB_FIXTURE_DIRS)
    def test_no_secrets_in_committed_fixtures(self, fixture_dir: str):
        """Committed CIB fixtures must not contain secrets."""
        cib_path = Path(fixture_dir) / "cib.xml"
        if not cib_path.exists():
            pytest.skip(f"Fixture not found: {cib_path}")

        content = cib_path.read_text()
        # Must not contain real Azure subscription GUIDs (allow zeroed GUIDs)
        import re
        guid_pattern = re.compile(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            re.IGNORECASE,
        )
        for match in guid_pattern.finditer(content):
            assert match.group() == "00000000-0000-0000-0000-000000000000", (
                f"Non-redacted GUID found in {cib_path}: {match.group()}"
            )

    @pytest.mark.parametrize("fixture_dir", CIB_FIXTURE_DIRS)
    def test_sanitized_cib_parseable(self, fixture_dir: str):
        """Sanitized CIB XML must still be parseable by lxml."""
        cib_path = Path(fixture_dir) / "cib.xml"
        if not cib_path.exists():
            pytest.skip(f"Fixture not found: {cib_path}")

        from lxml import etree

        tree = etree.parse(str(cib_path))
        root = tree.getroot()
        assert root.tag == "cib", f"Expected root tag 'cib', got '{root.tag}'"
        assert root.find(".//configuration") is not None
        assert root.find(".//resources") is not None
```

---

## 5. Release Supply Chain Security

These specifications ensure that every STAF release image is signed, includes an SBOM,
and has provenance attestation. This extends the release artifacts defined in the main
PRD [Stage 6: Release Gate](./PRD_E2E_TESTING.md#stage-6-release-gate-new).

**Cross-reference**: Main PRD §5 Stage 6 (Release Artifacts table), §9 (Security Considerations),
existing CI workflows in `.github/workflows/`.

### 5.1 Cosign Image Signing Workflow

All container images pushed to ACR during the release pipeline must be signed using
[cosign](https://github.com/sigstore/cosign) with keyless signing (Fulcio + Rekor).

```yaml
# Addition to .github/workflows/release.yml (Stage 6)
- name: Install cosign
  uses: sigstore/cosign-installer@v3

- name: Sign container image
  env:
    COSIGN_EXPERIMENTAL: "1"
  run: |
    IMAGE="${{ env.ACR_REGISTRY }}/staf:${{ steps.version.outputs.version }}"
    # Keyless signing via GitHub OIDC → Fulcio certificate → Rekor transparency log
    cosign sign \
      --yes \
      --oidc-issuer="https://token.actions.githubusercontent.com" \
      "$IMAGE@$(docker inspect --format='{{index .RepoDigests 0}}' "$IMAGE" | cut -d@ -f2)"

- name: Verify signature (smoke test)
  run: |
    IMAGE="${{ env.ACR_REGISTRY }}/staf:${{ steps.version.outputs.version }}"
    cosign verify \
      --certificate-oidc-issuer="https://token.actions.githubusercontent.com" \
      --certificate-identity-regexp="github.com/Azure/sap-automation-qa" \
      "$IMAGE"
```

### 5.2 SBOM Generation with Syft

Generate a Software Bill of Materials for every release image using
[syft](https://github.com/anchore/syft), attached to the GitHub Release as an asset.

```yaml
- name: Install syft
  uses: anchore/sbom-action/download-syft@v0

- name: Generate SBOM
  run: |
    IMAGE="${{ env.ACR_REGISTRY }}/staf:${{ steps.version.outputs.version }}"
    syft "$IMAGE" \
      --output spdx-json=sbom-staf-${{ steps.version.outputs.version }}.spdx.json \
      --output cyclonedx-json=sbom-staf-${{ steps.version.outputs.version }}.cdx.json

- name: Attach SBOM to cosign attestation
  run: |
    IMAGE="${{ env.ACR_REGISTRY }}/staf:${{ steps.version.outputs.version }}"
    cosign attest \
      --yes \
      --predicate sbom-staf-${{ steps.version.outputs.version }}.spdx.json \
      --type spdxjson \
      "$IMAGE"

- name: Upload SBOM to GitHub Release
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: |
    VERSION="${{ steps.version.outputs.version }}"
    gh release upload "v${VERSION}" \
      sbom-staf-${VERSION}.spdx.json \
      sbom-staf-${VERSION}.cdx.json
```

### 5.3 SLSA Provenance Attestation

Use the [SLSA GitHub Generator](https://github.com/slsa-framework/slsa-github-generator)
to produce SLSA Level 3 provenance for container images.

```yaml
# Separate job in release.yml — uses reusable workflow
provenance:
  needs: [release]
  permissions:
    actions: read
    id-token: write
    packages: write
  uses: slsa-framework/slsa-github-generator/.github/workflows/generator_container_slsa3.yml@v2.1.0
  with:
    image: ${{ needs.release.outputs.image }}
    digest: ${{ needs.release.outputs.digest }}
    registry-username: ${{ github.actor }}
  secrets:
    registry-password: ${{ secrets.GITHUB_TOKEN }}
```

### 5.4 Verification Commands for Consumers

Include these commands in release documentation so consumers can verify image integrity:

```bash
# 1. Verify image signature (keyless / Fulcio)
cosign verify \
  --certificate-oidc-issuer="https://token.actions.githubusercontent.com" \
  --certificate-identity-regexp="github.com/Azure/sap-automation-qa" \
  "${ACR_REGISTRY}/staf:${VERSION}"

# 2. Verify SBOM attestation
cosign verify-attestation \
  --certificate-oidc-issuer="https://token.actions.githubusercontent.com" \
  --certificate-identity-regexp="github.com/Azure/sap-automation-qa" \
  --type spdxjson \
  "${ACR_REGISTRY}/staf:${VERSION}"

# 3. Download and inspect SBOM
cosign verify-attestation \
  --certificate-oidc-issuer="https://token.actions.githubusercontent.com" \
  --certificate-identity-regexp="github.com/Azure/sap-automation-qa" \
  --type spdxjson \
  "${ACR_REGISTRY}/staf:${VERSION}" \
  | jq -r '.payload' | base64 -d | jq .

# 4. Verify SLSA provenance
slsa-verifier verify-image \
  --source-uri="github.com/Azure/sap-automation-qa" \
  --source-tag="v${VERSION}" \
  "${ACR_REGISTRY}/staf:${VERSION}"

# 5. Scan SBOM for vulnerabilities
grype sbom:sbom-staf-${VERSION}.spdx.json --fail-on critical
```

### 5.5 Supply Chain Security Gates

| Gate | Tool | Enforcement | Failure Action |
|------|------|-------------|----------------|
| Image signed | cosign verify | Release workflow | Block release |
| SBOM generated | syft | Release workflow | Block release |
| SBOM vulnerability scan | grype | Release workflow | Block on critical CVEs |
| Provenance attested | SLSA generator | Release workflow | Block release |
| Base image CVE-free | Trivy | Existing `trivy.yml` | Block PR merge |
| Dependency review | GitHub Dependency Review | Existing workflow | Block PR merge |
| OSSF Scorecard | scorecard-action | Existing workflow | Advisory (target ≥ 7.0) |

---

## 6. Self-Hosted Runner Hardening Checklist

This checklist applies to the Azure VM self-hosted runner described in the main PRD
[§4.1 Management Server](./PRD_E2E_TESTING.md#41-management-server-staf-host).
The runner has SSH access to SAP VMs and Azure Managed Identity credentials, making
it a high-value target (see Risk R-007 in main PRD §11).

### 6.1 VM Image Requirements

| Requirement | Specification | Verification |
|------------|---------------|--------------|
| **Base OS** | Ubuntu 22.04 LTS (or Azure Linux) | `lsb_release -a` |
| **Hardened image** | CIS Level 1 benchmark applied | CIS-CAT scan |
| **No GUI** | Server (minimal) installation | `dpkg -l | grep -c xorg` returns 0 |
| **Unattended upgrades** | Enabled for security updates | `systemctl is-enabled unattended-upgrades` |
| **SSH hardening** | `PermitRootLogin no`, key-only auth, `MaxAuthTries 3` | `sshd -T` |
| **NTP sync** | `chrony` or `systemd-timesyncd` configured | `timedatectl status` |
| **Disk encryption** | Azure Disk Encryption (ADE) or host-based encryption | `az vm encryption show` |
| **Swap disabled** | No swap file (prevents secret leakage to disk) | `swapon --show` returns empty |

### 6.2 Network Security (NSG Rules)

#### Inbound Rules

| Priority | Source | Destination | Port | Protocol | Action | Purpose |
|----------|--------|-------------|------|----------|--------|---------|
| 100 | AzureCloud (GitHub Actions) | Runner VM | 443 | TCP | Allow | Runner registration & polling |
| 200 | Management subnet CIDR | Runner VM | 22 | TCP | Allow | Admin SSH (break-glass only) |
| 4096 | Any | Any | Any | Any | **Deny** | Default deny all inbound |

#### Outbound Rules

| Priority | Source | Destination | Port | Protocol | Action | Purpose |
|----------|--------|-------------|------|----------|--------|---------|
| 100 | Runner VM | SAP subnet CIDR | 22 | TCP | Allow | SSH to SAP VMs |
| 200 | Runner VM | AzureKeyVault | 443 | TCP | Allow | Key Vault access |
| 300 | Runner VM | AzureContainerRegistry | 443 | TCP | Allow | ACR pull/push |
| 400 | Runner VM | AzureMonitor | 443 | TCP | Allow | Log Analytics, ADX |
| 500 | Runner VM | AzureActiveDirectory | 443 | TCP | Allow | MI token acquisition |
| 600 | Runner VM | github.com, *.actions.githubusercontent.com | 443 | TCP | Allow | Runner comms, action downloads |
| 700 | Runner VM | pypi.org, files.pythonhosted.org | 443 | TCP | Allow | Python packages |
| 800 | Runner VM | registry-1.docker.io, *.docker.io | 443 | TCP | Allow | Docker images |
| 4096 | Any | Any | Any | Any | **Deny** | Default deny all other egress |

#### Network Monitoring

```bash
# Detect unexpected outbound connections (run daily via cron)
ss -tnp | grep ESTAB | \
  awk '{print $5}' | cut -d: -f1 | sort -u | \
  while read -r ip; do
    if ! grep -q "$ip" /etc/staf/allowed_destinations.txt; then
      logger -t staf-security "ALERT: Unexpected outbound connection to $ip"
    fi
  done
```

### 6.3 Identity & Access Management

| Control | Configuration | Verification |
|---------|--------------|--------------|
| **System-assigned MI** | Enabled on runner VM | `az vm identity show` |
| **MI scope (Key Vault)** | `Key Vault Secrets User` on E2E Key Vault only | `az role assignment list --assignee <MI-OID>` |
| **MI scope (ACR)** | `AcrPull` (or `AcrPush` for release only) | Same |
| **MI scope (LAWS)** | `Log Analytics Contributor` on E2E workspace only | Same |
| **MI scope (ADX)** | `Database Ingestor` on E2E database only | Same |
| **MI scope (Compute)** | `Reader` on SAP resource groups only | Same |
| **No service principals** | All Azure auth via MI — zero stored secrets | `az ad sp list --filter` returns none for runner |
| **PIM JIT elevation** | Admin roles require PIM activation (max 4 hours) | Azure PIM policy |
| **Conditional Access** | MFA required for interactive logins to management subscription | Entra ID CA policy |
| **Runner token scope** | GitHub PAT scoped to `repo` only, not `admin:org` | Token settings |

### 6.4 Monitoring & Detection

| Control | Tool | Configuration |
|---------|------|---------------|
| **EDR agent** | Microsoft Defender for Servers (P2) | Auto-enrolled via Azure Security Center |
| **auditd rules** | Linux Audit Framework | See rules below |
| **File integrity monitoring** | Defender for Servers FIM | Monitor `/etc/`, `/usr/bin/`, runner binaries |
| **Log forwarding** | Azure Monitor Agent (AMA) | Syslog + auditd → Log Analytics |
| **Alert rules** | Azure Monitor | SSH brute-force, new outbound connection, privilege escalation |
| **Vulnerability scanning** | Defender for Servers | Daily vulnerability assessment |

#### auditd Rules for Runner VM

```bash
# /etc/audit/rules.d/staf-runner.rules

# Monitor SSH key access (SAP credentials)
-w /home/runner/.ssh/ -p rwa -k ssh_key_access

# Monitor Docker socket
-w /var/run/docker.sock -p rwa -k docker_access

# Monitor runner configuration
-w /home/runner/actions-runner/.credentials -p rwa -k runner_creds

# Monitor sudo usage
-w /etc/sudoers -p wa -k sudoers_change
-w /etc/sudoers.d/ -p wa -k sudoers_change

# Monitor cron changes
-w /etc/crontab -p wa -k cron_change
-w /etc/cron.d/ -p wa -k cron_change

# Monitor user/group changes
-w /etc/passwd -p wa -k user_change
-w /etc/group -p wa -k group_change

# Monitor kernel module loading (detect rootkits)
-a always,exit -F arch=b64 -S init_module -S finit_module -k kernel_module

# Monitor network configuration changes
-w /etc/hosts -p wa -k network_change
-w /etc/resolv.conf -p wa -k network_change
-w /etc/sysconfig/iptables -p wa -k firewall_change
```

#### KQL Alert Queries (Log Analytics)

```kusto
// Unusual SSH activity on runner VM
Syslog
| where Computer == "staf-e2e-runner"
| where Facility == "auth" and SyslogMessage has "Failed password"
| summarize FailedAttempts = count() by bin(TimeGenerated, 5m), SrcIP = extract(@"from (\S+)", 1, SyslogMessage)
| where FailedAttempts > 5

// Privilege escalation detection
AuditLog_CL
| where Computer_s == "staf-e2e-runner"
| where key_s == "sudoers_change" or key_s == "user_change"
| project TimeGenerated, User = uid_s, Action = syscall_s, File = name_s

// Unexpected Docker image pulls
ContainerLog
| where Computer == "staf-e2e-runner"
| where LogEntry has "pull" and LogEntry !has "staf"
| project TimeGenerated, LogEntry
```

### 6.5 Maintenance Schedule

| Task | Frequency | Method | Owner |
|------|-----------|--------|-------|
| **OS patching** | Weekly (Tue 02:00 UTC) | Azure Update Manager | Infra |
| **Runner binary update** | Monthly (with runner releases) | `./config.sh --update` | DevOps |
| **Docker image prune** | Daily (via cron) | `docker system prune -af --filter "until=72h"` | Automated |
| **Log rotation** | Daily | logrotate (10 MB, 5 backups) | Automated |
| **Disk usage check** | Hourly (via cron) | Alert if `/` > 85% or `/var/lib/docker` > 80% | Monitoring |
| **Credential rotation audit** | Quarterly | Review MI role assignments, runner token | Security |
| **CIS benchmark rescan** | Quarterly | CIS-CAT or Azure Policy guest configuration | Security |
| **Incident response drill** | Semi-annual | Simulate compromised runner, verify containment | Security |

#### Automated Cleanup Cron

```bash
# /etc/cron.d/staf-runner-cleanup
# Daily Docker cleanup (remove dangling images, stopped containers, unused volumes)
0 3 * * * runner docker system prune -af --filter "until=72h" >> /var/log/staf-cleanup.log 2>&1

# Weekly: remove old GitHub Actions working directories
0 4 * * 0 runner find /home/runner/actions-runner/_work -maxdepth 2 -mtime +7 -type d -exec rm -rf {} + 2>/dev/null

# Hourly: disk usage alert
0 * * * * runner bash -c 'USAGE=$(df / --output=pcent | tail -1 | tr -d " %"); [ "$USAGE" -gt 85 ] && logger -t staf-disk "ALERT: Root disk usage at ${USAGE}%"'
```

### 6.6 Runner Isolation Recommendations

| Control | Description |
|---------|-------------|
| **Ephemeral runner mode** | Use `--ephemeral` flag so each job gets a clean runner instance. The VM is re-imaged after each workflow run. |
| **Dedicated runner group** | Create a GitHub runner group `sap-e2e` with repository-level scope (not org-wide). |
| **Label-based routing** | Use labels `[self-hosted, sap-e2e]` to ensure only E2E workflows target this runner. |
| **No shared state** | Runner `_work` directory cleared between jobs; no persistent caches. |
| **Service account** | Runner process runs as `runner` user (not root); `runner` user has no sudo access except for Docker. |

---

## Appendix: Integration with Main PRD Stages

| This Document Section | Integrates Into | How |
|----------------------|----------------|-----|
| §2 API Security Tests | Stage 3 (API Smoke) | Run as `test_api_security.py` after functional smoke tests |
| §3 Container Security | Stage 2 (Container Integration) | Run `test_container_security.sh` after CI-001..CI-013 |
| §4 CIB Sanitization | Stage 4 (Offline Validation) | Pre-commit hook + CI check on CIB fixture files |
| §5 Supply Chain | Stage 6 (Release Gate) | Added steps in `release.yml` after image push |
| §6 Runner Hardening | Infrastructure (§4.1) | Operational checklist applied during runner provisioning |

---

> **Next Steps**:
> 1. Review with engineering and security leads.
> 2. Implement SEC-001 through SEC-010 in `tests/e2e/test_api_security.py`.
> 3. Add CRT checks to `tests/e2e/test_container_security.sh`.
> 4. Integrate cosign + syft into the release workflow.
> 5. Apply runner hardening checklist during self-hosted runner setup (Phase 3).
