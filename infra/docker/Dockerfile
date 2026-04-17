# =============================================================================
# AppScan Custom Dashboard — Multi-stage Docker image
# Stage 1: Build React frontend
# Stage 2: Python backend + pre-built frontend
# =============================================================================

# --- Stage 1: Frontend build ---
FROM node:20-alpine AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Production image ---
FROM python:3.12-slim AS production

# Prevent Python from writing .pyc and enable unbuffered stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies for psycopg (libpq) and cleanup
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq5 && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir . && \
    pip install --no-cache-dir gunicorn

# Copy backend source
COPY backend/app/ ./app/
COPY backend/migrations/ ./migrations/
COPY backend/alembic.ini ./

# Copy pre-built frontend from stage 1
COPY --from=frontend-build /build/frontend/dist/ ./frontend/dist/

# Create non-root user
RUN groupadd -r dashboard && useradd -r -g dashboard -d /app -s /sbin/nologin dashboard && \
    mkdir -p /app/data/exports && \
    chown -R dashboard:dashboard /app
USER dashboard

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Run with gunicorn + uvicorn workers for production
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--timeout", "120", \
     "--access-logfile", "-"]
