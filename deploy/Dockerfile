# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1: Build stage — install Python deps into an isolated venv
# ---------------------------------------------------------------------------
FROM mcr.microsoft.com/azurelinux/base/python:3.12 AS builder
WORKDIR /build

RUN tdnf install -y gcc libffi-devel && tdnf clean all

# Copy only the lockfile — layer is cached until requirements-prod.txt changes
COPY requirements-prod.txt .

RUN python3 -m venv /opt/venv && . /opt/venv/bin/activate \
    && pip install --upgrade pip

RUN --mount=type=cache,target=/root/.cache/pip \
    . /opt/venv/bin/activate \
    && pip install -r requirements-prod.txt

# ---------------------------------------------------------------------------
# Stage 2: Runtime
# ---------------------------------------------------------------------------
FROM mcr.microsoft.com/azurelinux/base/python:3.12

# Layer 1 — OS packages (rarely changes)
RUN tdnf update -y && tdnf install -y \
    openssh-clients \
    git \
    curl \
    util-linux \
    gawk \
    shadow-utils \
    && tdnf clean all \
    && ln -sf /usr/bin/python3 /usr/bin/python

# Layer 2 — azure-cli (cached independently from source code changes)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install azure-cli

# Layer 3 — non-root user
RUN groupadd --gid 1000 appgroup \
    && useradd --uid 1000 --gid appgroup --shell /bin/bash \
        --create-home --home-dir /app appuser \
    && mkdir -p /app/.ssh \
    && chmod 700 /app/.ssh \
    && chown -R appuser:appgroup /app

WORKDIR /app

# Layer 4 — Python venv (changes only when dependencies change)
COPY --from=builder --chown=appuser:appgroup /opt/venv /opt/venv

# Layer 5 — source code (changes most frequently — keep last)
COPY --chown=appuser:appgroup src/ ./src/
COPY --chown=appuser:appgroup scripts/ ./scripts/
COPY --chown=appuser:appgroup VERSION ./VERSION

ENV PATH="/opt/venv/bin:$PATH"
ENV VIRTUAL_ENV=/opt/venv
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV HOME=/app

USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1
EXPOSE 8000 8001 8080
CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000"]