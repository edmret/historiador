# ── Build stage ──────────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

WORKDIR /build

# Copy only pyproject.toml first (for layer caching)
COPY pyproject.toml uv.lock ./

# Install deps into a virtualenv
RUN uv sync --frozen --no-install-project

# Copy the project
COPY backend/ backend/
COPY scripts/ scripts/

# ── Production stage ────────────────────────────────────────────────────────
FROM python:3.13-slim AS production

# Non-root user
RUN useradd --create-home --shell /bin/bash historian
WORKDIR /home/historian

# Copy uv-installed packages from builder
COPY --from=builder /build/.venv /home/historian/.venv

# Copy app files
COPY --from=builder /build/backend/ /home/historian/backend/
COPY --from=builder /build/scripts/ /home/historian/scripts/

# Copy frontend static files
COPY frontend/ /home/historian/frontend/

# Create data directory for SQLite
RUN mkdir -p /home/historian/data && chown -R historian:historian /home/historian

USER historian

ENV PATH="/home/historian/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/auth/config')" || exit 1

# Start the server (no --reload in production)
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]