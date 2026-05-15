# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

# ---------------------------------------------------------------------------
# Stage 1: Build stage — install Python deps into an isolated venv
# ---------------------------------------------------------------------------
FROM mcr.microsoft.com/azurelinux/base/python:3.12 AS builder
WORKDIR /build

RUN tdnf install -y --nogpgcheck libffi-devel && tdnf clean all

# Copy requirements — layer is cached until requirements change
COPY requirements.in .

RUN python3 -m venv /opt/venv && . /opt/venv/bin/activate \
    && pip install --upgrade pip

RUN . /opt/venv/bin/activate \
    && pip install --no-cache-dir -r requirements.in

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
RUN pip install --no-cache-dir azure-cli

# Layer 3 — non-root user
RUN groupadd --gid 1000 appgroup \
    && useradd --uid 1000 --gid appgroup --shell /bin/bash \
        --create-home --home-dir /app appuser \
    && mkdir -p /app/.ssh /app/.cache/huggingface \
    && chmod 700 /app/.ssh \
    && chown -R appuser:appgroup /app

WORKDIR /app

# Layer 4 — Python venv (changes only when dependencies change)
COPY --from=builder --chown=appuser:appgroup /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH"
ENV VIRTUAL_ENV=/opt/venv
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV HOME=/app
ENV HF_HOME=/app/.cache/huggingface
ENV HF_HUB_OFFLINE=1
ENV EMBEDDING_MODEL_PATH=/app/models/e5-base-v2

# Layer 5 — embedding model (cached until model files change)
COPY --chown=appuser:appgroup models/e5-base-v2 /app/models/e5-base-v2

# Layer 6 — source code (changes most frequently — keep last)
COPY --chown=appuser:appgroup src/ ./src/
COPY --chown=appuser:appgroup scripts/ ./scripts/
COPY --chown=appuser:appgroup VERSION ./VERSION

ARG GIT_COMMIT=unknown
RUN echo "$GIT_COMMIT" > /app/GIT_COMMIT

USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -sf -o /dev/null -w '%{http_code}' http://localhost:8001/mcp | grep -qE '^[2-5]' || exit 1
EXPOSE 8000 8001
CMD ["uvicorn", "src.mcp_server.server:http_app", "--host", "0.0.0.0", "--port", "8001"]