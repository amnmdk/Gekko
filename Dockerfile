# ============================================================
# ndbot — Dockerfile
# Base: python:3.11-slim  (ARM64 compatible for Raspberry Pi 5)
# ============================================================
FROM python:3.11-slim

# Metadata
LABEL maintainer="ndbot"
LABEL description="News-Driven Intraday Trading Research Framework"
LABEL version="0.1.0"

# Build args
ARG TARGETPLATFORM
ARG BUILDPLATFORM

# System deps (minimal for Pi compatibility)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r ndbot && useradd -r -g ndbot ndbot

# Working directory
WORKDIR /app

# Install Python dependencies (layer-cached)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy project source
COPY src/ ./src/
COPY config/ ./config/
COPY pyproject.toml .

# Install the package in editable mode
RUN pip install --no-cache-dir -e .

# Create data / results directories with correct ownership
RUN mkdir -p /app/data /app/results && \
    chown -R ndbot:ndbot /app

# Switch to non-root user
USER ndbot

# Health check — verify CLI entry point works
HEALTHCHECK --interval=60s --timeout=10s --start-period=5s --retries=3 \
    CMD ndbot --version || exit 1

# Default command: show help
ENTRYPOINT ["ndbot"]
CMD ["--help"]
