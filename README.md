# Archaeological Research & Heritage Management Platform

A centralised database for researchers, universities, museums and excavation
projects to store, search, visualise and manage archaeological information.

> **Status: milestone 1 of 5 — backend, database schema, authentication and
> Docker.** The frontend, media handling, GIS endpoints and the remaining
> modules land in later milestones. See [Roadmap](#roadmap).

---

## Architecture

```
   ┌──────────────────────────────────────┐
   │  Frontend — React + TypeScript       │   (milestone 2)
   └──────────────────┬───────────────────┘
                      │  HTTPS / JSON
   ┌──────────────────▼───────────────────┐
   │  Backend API — FastAPI + SQLAlchemy  │   ◀── you are here
   │  auth · permissions · validation     │
   └──────────────────┬───────────────────┘
                      │  (the only path to the data)
   ┌──────────────────▼───────────────────┐
   │  PostgreSQL 16 + PostGIS 3.4         │
   └──────────────────────────────────────┘
```

The database is never reachable from a client. It is not published to the host
in the default Compose file either — the backend is its only consumer, which is
what makes the permission model meaningful rather than advisory.

| Layer | Technology |
|-------|-----------|
| API | Python 3.12, FastAPI, SQLAlchemy 2.0, Pydantic v2 |
| Database | PostgreSQL 16, PostGIS 3.4 |
| Auth | JWT (HS256) access + rotating refresh tokens, bcrypt |
| Migrations | Alembic |
| Files | Local disk behind a storage interface, ready for S3/GCS |
| Frontend | React + TypeScript, Leaflet + OpenStreetMap *(milestone 2)* |

---

## Quick start

```bash
git clone <this repository>
cd deep

cp .env.example .env
# Edit .env: set SECRET_KEY, POSTGRES_PASSWORD and FIRST_ADMIN_PASSWORD.
# Generate a good secret with:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"

docker compose up --build
```

That is all. On first boot the stack will:

1. start PostgreSQL and enable PostGIS,
2. wait for it to accept queries,
3. apply all migrations,
4. seed reference data and the first administrator,
5. serve the API on <http://localhost:8000>.

| What | Where |
|------|-------|
| API | <http://localhost:8000> |
| Interactive docs (Swagger) | <http://localhost:8000/docs> |
| Reference docs (ReDoc) | <http://localhost:8000/redoc> |
| OpenAPI schema | <http://localhost:8000/api/v1/openapi.json> |
| Liveness / readiness | `/api/v1/health`, `/api/v1/ready` |

Sign in with the `FIRST_ADMIN_EMAIL` and `FIRST_ADMIN_PASSWORD` from your
`.env`, then change the password.

### Sample data

Set `SEED_SAMPLE_DATA=true` in `.env` to get a demonstration project — one
site, two stratigraphically related contexts and three artifacts — plus
accounts for each role (`e.marchetti` researcher, `j.okonkwo` student,
`visitor`), all with the password `DemoPass!2024`.

Sample data is refused when `ENVIRONMENT=production`.

### Running without Docker

See [`backend/README.md`](backend/README.md).

---

## What milestone 1 delivers

**Database schema — 25 tables, complete for every module in the specification.**
Projects, sites, artifacts and excavation contexts; photographs, documents and
3D models; GIS layers and features; controlled vocabularies for periods,
materials and object categories; publications; and the cross-cutting tables for
permissions, revisions, activity, notifications and comments. Later milestones
add endpoints over this schema — they do not need to reshape it.

**Authentication.** Registration, login by e-mail or username, JWT access
tokens, rotating refresh tokens with reuse detection, session listing and
revocation, password change, administrative reset, and account lockout after
repeated failures.

**Authorisation.** A single policy module combining global roles, project
membership and per-record grants, with the student-approval workflow built in.
It is covered by 40 tests because every later milestone depends on it being
right.

**Operations.** Multi-stage Docker build running as a non-root user,
health-checked Compose stack, automatic migration and seeding on start, and a
nightly `pg_dump` service with retention.

### Endpoints so far

| Method | Path | Who |
|--------|------|-----|
| `GET` | `/api/v1/health`, `/api/v1/ready` | anyone |
| `POST` | `/api/v1/auth/register` | anyone |
| `POST` | `/api/v1/auth/login`, `/auth/token` | anyone |
| `POST` | `/api/v1/auth/refresh` | valid refresh token |
| `POST` | `/api/v1/auth/logout` | signed in |
| `GET` | `/api/v1/auth/me` | signed in |
| `GET`/`DELETE` | `/api/v1/auth/sessions[/{id}]` | signed in |
| `POST` | `/api/v1/auth/change-password` | signed in |
| `GET` | `/api/v1/users` | signed in |
| `PATCH` | `/api/v1/users/me` | signed in |
| `GET` | `/api/v1/users/{id}` | self or admin |
| `POST`/`PATCH`/`DELETE` | `/api/v1/users[/{id}]` | admin |
| `POST` | `/api/v1/users/{id}/reset-password` | admin |

---

## Roles

| | visitor | student | researcher | admin |
|---|:---:|:---:|:---:|:---:|
| Browse public records, search, map | ✅ | ✅ | ✅ | ✅ |
| Create records, upload images | ❌ | ✅ | ✅ | ✅ |
| Edit own records | ❌ | ✅ | ✅ | ✅ |
| Edit others' records in a project | ❌ | ❌ | ✅ | ✅ |
| Create projects, approve submissions | ❌ | ❌ | ✅ | ✅ |
| Delete a project | ❌ | ❌ | director only | ✅ |
| Manage users, roles, settings | ❌ | ❌ | ❌ | ✅ |

Student submissions start as `pending` and stay invisible to readers until a
researcher on the same project approves them.

---

## Backups

The `backup` service dumps the database on a schedule (daily by default) into
the `backups` volume, in PostgreSQL's custom format, pruning dumps older than
`BACKUP_RETENTION_DAYS`.

```bash
# List
docker compose exec backup ls -lh /backups

# Restore
docker compose exec -T backup \
  pg_restore --clean --if-exists -d "$POSTGRES_DB" /backups/<file>.dump
```

The dump runs in the same image as the server, so `pg_dump` and the server
version always match — a mismatch is the usual reason a restore fails when it
is needed most.

---

## Configuration

Everything is environment variables; see [`.env.example`](.env.example) for the
full annotated list. The ones that matter:

| Variable | Notes |
|----------|-------|
| `SECRET_KEY` | **Required.** Signs every JWT. Changing it signs everyone out. |
| `POSTGRES_PASSWORD` | **Required.** Refused in production if left at a default. |
| `FIRST_ADMIN_PASSWORD` | **Required.** Change it after first sign-in. |
| `ENVIRONMENT` | `production` turns on HSTS and rejects default secrets |
| `CORS_ORIGINS` | Comma-separated origins allowed from a browser |
| `SEED_SAMPLE_DATA` | Demonstration project; ignored in production |
| `RUN_MIGRATIONS` / `RUN_SEED` | Both default to `true` and are safe to repeat |

---

## Development

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

pytest                              # 108 tests
pytest --cov=app                    # coverage
ruff check app tests scripts        # lint
alembic revision --autogenerate -m "…"   # after editing models
```

Tests need a PostgreSQL with PostGIS; they create and drop their own database.

---

## Roadmap

| Milestone | Contents |
|-----------|----------|
| **1 — done** | Backend skeleton, full schema, auth, permissions, Docker, backups |
| 2 | CRUD for projects, sites, artifacts and contexts; revision history; activity feed; search |
| 3 | File uploads, thumbnails, EXIF, documents, 3D models, QR codes |
| 4 | GIS endpoints, GeoJSON/Shapefile/KML import and export, spatial search |
| 5 | React frontend: dashboard, map, forms, dark/light mode, admin panel |

Later: AI-assisted classification and image tagging, OCR, satellite and drone
imagery, LiDAR, offline field collection.

---

## Licence

MIT.
