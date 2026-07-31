# syntax=docker/dockerfile:1
#
# Two-stage build: wheels are compiled in a builder image that carries the
# toolchain, and only the resulting site-packages are copied into a slim
# runtime image. That keeps compilers out of production and the image small.

# --------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ``build-essential`` and ``libpq-dev`` are needed by any dependency without a
# manylinux wheel for this platform; they never reach the runtime image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install -r requirements.txt

# --------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    STORAGE_ROOT=/data/uploads

# ``libpq5`` is the runtime half of libpq-dev; ``curl`` backs the healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Run as an unprivileged user. A fixed uid/gid keeps ownership predictable on
# bind-mounted volumes across hosts.
RUN groupadd --gid 1000 archeo \
    && useradd --uid 1000 --gid archeo --create-home --shell /bin/bash archeo

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=archeo:archeo . .

RUN mkdir -p /data/uploads /data/backups \
    && chown -R archeo:archeo /data \
    && chmod +x /app/docker/entrypoint.sh

USER archeo

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/v1/health || exit 1

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
