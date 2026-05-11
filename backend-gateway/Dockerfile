# Multi-stage build for FastAPI backend gateway
# Stage 1: Build dependencies
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build-time system deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps into a virtual env for clean copy
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Production image (no gcc, no build tools)
FROM python:3.12-slim AS production

WORKDIR /app

# Copy only the virtual env from builder (no gcc/build deps in final image)
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code and alembic migrations
COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini .

# Create non-root user
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Run with multiple workers for production
CMD ["uvicorn", "app.main:socket_app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--loop", "uvloop", "--http", "httptools"]
