# syntax=docker/dockerfile:1
#
# Two-stage build: dependencies are installed into a virtual environment in the
# builder, and only that environment is copied into a slim runtime image, so
# pip's cache and metadata never ship.
#
# Deliberately no ``apt-get`` in either stage. Every dependency resolves to a
# prebuilt wheel — psycopg[binary] bundles its own libpq, and Pillow, bcrypt and
# uvloop all publish manylinux wheels — so there is nothing to compile and
# nothing to install from a distribution mirror. That removes the build's
# largest download (a ~77 MB compiler toolchain) and its most common failure:
# a mirror serving a corrupted package, which surfaces as "Hash Sum mismatch"
# and has nothing to do with this project.

# --------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
COPY requirements.txt .

# ``--only-binary=:all:`` makes the no-compiler assumption explicit: if a future
# dependency ships no wheel, the build fails here with a clear message rather
# than dying halfway through a compile. The fix at that point is either a
# version that does publish wheels, or reinstating build-essential above.
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install --only-binary=:all: -r requirements.txt

# --------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    STORAGE_ROOT=/data/uploads

# Run as an unprivileged user. A fixed uid/gid keeps ownership predictable on
# bind-mounted volumes across hosts.
RUN groupadd --gid 1000 archeo \
    && useradd --uid 1000 --gid archeo --create-home --shell /bin/bash archeo

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=archeo:archeo . .

# The `sed` is not decoration. Git for Windows converts text files to CRLF on
# checkout by default, and a shell script converted that way begins
#
#     #!/usr/bin/env bash\r
#
# so Linux looks for an interpreter literally called "bash\r" and the container
# exits before it has run a line. From the outside all anybody sees is
# `container archeo-api is unhealthy`, which names neither the file nor the
# reason — and the build succeeded, so it looks like the platform's fault.
#
# `.gitattributes` pins these files to LF in the repository, which fixes it at
# the source. This fixes it for a working copy that already has CRLF, which is
# every copy checked out before that file existed.
RUN mkdir -p /data/uploads /data/backups \
    && chown -R archeo:archeo /data \
    && sed -i 's/\r$//' /app/docker/entrypoint.sh \
    && chmod +x /app/docker/entrypoint.sh

USER archeo

EXPOSE 8000

# Python's standard library rather than curl, so the runtime image needs no
# package manager either.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health', timeout=4)"]

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
