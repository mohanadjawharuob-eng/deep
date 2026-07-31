# Archaeological Research & Heritage Management Platform

A centralised database for researchers, universities, museums and excavation
projects to store, search, visualise and manage archaeological information.

> **Status: milestone 2 of 5 — records, history, activity and search.**
> The API now manages projects, sites, artifacts and excavation contexts, with
> version history, an approval workflow, an audit feed and global search. File
> uploads, GIS endpoints and the frontend land in later milestones. See
> [Roadmap](#roadmap).

---

## Architecture

```
   ┌──────────────────────────────────────┐
   │  Frontend — React + TypeScript       │   (milestone 5)
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
| Frontend | React + TypeScript, Leaflet + OpenStreetMap *(milestone 5)* |

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

## What is built

### Milestone 1 — foundations

**Database schema — 25 tables, complete for every module in the specification.**
Projects, sites, artifacts and excavation contexts; photographs, documents and
3D models; GIS layers and features; controlled vocabularies for periods,
materials and object categories; publications; and the cross-cutting tables for
permissions, revisions, activity, notifications and comments.

**Authentication.** Registration, login by e-mail or username, JWT access
tokens, rotating refresh tokens with reuse detection, session listing and
revocation, password change, administrative reset, and account lockout.

**Authorisation.** One policy module combining global roles, project membership
and per-record grants, with the student-approval workflow built in.

**Operations.** Multi-stage Docker build running as a non-root user,
health-checked Compose stack, automatic migration and seeding on start, and a
nightly `pg_dump` service with retention.

### Milestone 2 — records, history and search

**CRUD for the four core record types** — projects (with team management),
sites, artifacts and excavation contexts — each with filtering, sorting and
pagination, and each validated before it reaches the database.

**Version history.** Every record is snapshotted on creation and before every
change, so its history reaches back to the original state rather than to the
first edit. Any version can be restored, and the restore is itself a new
version — nothing is ever overwritten irrecoverably. A record's final state
survives its deletion.

**Approval workflow.** Student submissions enter a pending queue, stay out of
public listings until approved, and notify the project's researchers. Approving
requires both the researcher role and rights on that particular project.

**Activity feed.** Every write, sign-in and review decision is logged with the
fields that changed, scoped so users see their own actions plus activity in
projects they belong to.

**Global search** across all four record types at once, with free text and
structured filters (period, material, institution, researcher, country, date
range, bounding box), plus type-ahead suggestions.

**Stratigraphy.** Harris-matrix relationships between contexts, stored in both
directions automatically so the matrix cannot become one-sided.

Two decisions worth calling out, because both are easy to get wrong:

- **Listings filter in SQL, not in Python.** A permission check that loads rows
  and then discards them neither paginates nor scales. The policy is therefore
  written twice — once for a single loaded record, once as a SQL predicate — and
  `tests/test_visibility_sql.py` asserts the two agree across a matrix of users,
  records and review states, so they cannot drift apart.
- **Restricted site coordinates are blurred** for anyone who cannot edit the
  site, in the site endpoints *and* in search, because looting follows
  publication.

### Endpoints

| Method | Path | Who |
|--------|------|-----|
| `GET` | `/health`, `/ready` | anyone |
| `POST` | `/auth/register`, `/auth/login`, `/auth/refresh` | anyone |
| `GET`/`POST` | `/auth/me`, `/auth/sessions`, `/auth/logout`, `/auth/change-password` | signed in |
| `GET`/`PATCH` | `/users`, `/users/me`, `/users/{id}` | signed in / self / admin |
| `POST`/`DELETE` | `/users`, `/users/{id}`, `/users/{id}/reset-password` | admin |
| `GET` | `/projects`, `/sites`, `/artifacts`, `/contexts` | anyone, scoped by permission |
| `POST`/`PATCH`/`DELETE` | the same paths, with `/{id}` | per the role table below |
| `GET`/`POST`/`PATCH`/`DELETE` | `/projects/{id}/members[/{user_id}]` | project editors |
| `GET`/`POST`/`DELETE` | `/contexts/{id}/relationships[/{rel_id}]` | context editors |
| `GET` | `/artifacts/by-token/{token}` | anyone, scoped — resolves a QR label |
| `GET` | `/{kind}/{id}/revisions[/{version}]` | anyone who can read the record |
| `POST` | `/{kind}/{id}/revisions/{version}/restore` | anyone who can edit it |
| `GET` | `/activity`, `/{kind}/{id}/activity` | signed in, scoped |
| `GET` | `/pending` | researchers and admins |
| `POST` | `/{kind}/{id}/submit`, `/approve`, `/reject` | author / reviewer |
| `GET` | `/search`, `/search/suggest` | anyone, scoped |
| `GET` | `/taxonomy/periods`, `/materials`, `/categories` | anyone |
| `POST`/`PATCH`/`DELETE` | the same `/taxonomy/…` paths | admin |
| `GET`/`POST`/`DELETE` | `/notifications…` | signed in, own inbox only |

Everything is under `/api/v1`. `{kind}` is one of `projects`, `sites`,
`artifacts` or `contexts`.

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

pytest                              # 324 tests
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
| **2 — done** | CRUD for projects, sites, artifacts and contexts; revision history; approval workflow; activity feed; search |
| 3 | File uploads, thumbnails, EXIF, documents, 3D models, QR code images |
| 4 | GIS endpoints, GeoJSON/Shapefile/KML import and export, spatial search |
| 5 | React frontend: dashboard, map, forms, dark/light mode, admin panel |

Later: AI-assisted classification and image tagging, OCR, satellite and drone
imagery, LiDAR, offline field collection.

---

## Licence

MIT.
