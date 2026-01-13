# SAP Automation QA Backend
# Multi-stage build for smaller final image

FROM mcr.microsoft.com/oss/python/python:3.10 as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Final stage
FROM mcr.microsoft.com/oss/python/python:3.10-slim

WORKDIR /app

# Install runtime dependencies (ansible needs ssh, git for some operations)
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /app/data /app/logs /root/.ssh \
    && chmod 700 /root/.ssh

# Copy Python packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy application code
COPY src/ ./src/
COPY docs/ ./docs/
COPY WORKSPACES/ ./WORKSPACES/

# Create data directory for SQLite
RUN mkdir -p /app/data

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose port
EXPOSE 8000

# Run with uvicorn
CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
