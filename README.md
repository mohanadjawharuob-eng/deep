# Archaeological Research & Heritage Management Platform

A centralised database for researchers, universities, museums and excavation
projects to store, search, visualise and manage archaeological information.

> **Status: the museum module is complete, and the platform has its design.**
> The archaeology module is complete. The museum module catalogues accessioned
> objects in **your own accession numbering**, with conservation history,
> exhibitions, loans and environmental monitoring — and serves its cataloguing
> form as data, so the interface renders a FileMaker-style layout rather than
> carrying its own hard-coded copy of it.
>
> The web interface runs, and carries the **Stratum** design: earth over neon,
> drawn from fired clay, bone and oxidised bronze, in a light and a dark theme
> that are drawn separately rather than inverted. A catalogue can be imported
> from a spreadsheet with every column verified before a row is written, and the
> store can be **drawn as a floor plan** whose cases show what they hold.
>
> To try it: double-click **`Start Stratum.cmd`** on Windows, or run
> `bash start.sh` on macOS and Linux. Full instructions, written for somebody
> who does not write software, are in
> **[Running the platform locally](docs/running-locally.md)**. To let colleagues
> reach it, see **[Letting other people use it](docs/deploying.md)**. To let it
> send password resets and invitations, see
> **[Letting the platform send e-mail](docs/email-setup.md)** — optional, and
> the platform runs perfectly well without it.

---

## Architecture

```
   ┌──────────────────────────────────────┐
   │  Frontend — React + TypeScript       │   (built, unstyled)
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
| GIS | PostGIS geometry; GeoJSON, KML and shapefile interchange |
| Frontend | React + TypeScript, Vite, Leaflet + OpenStreetMap; hand-written CSS over design tokens, no UI library |

---

## Quick start

**New to this, or not a developer?** Follow [`SETUP.md`](SETUP.md) instead — it
covers installing Docker, downloading the code and signing in, with nothing
assumed.

```bash
git clone <your repo url>
cd deep

bash setup.sh          # Windows: powershell -ExecutionPolicy Bypass -File setup.ps1
docker compose up --build
```

`setup.sh` writes `.env` with a strong random `SECRET_KEY`, database password
and admin password, and prints the admin password for you. To configure it by
hand instead, copy `.env.example` to `.env` and fill in those three values
yourself — the stack refuses to start on the placeholders.

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

**Database schema — 36 tables**, covering the archaeology and museum modules
in full.
Projects, sites, artifacts and excavation contexts; photographs, documents and
3D models; GIS layers and features; controlled vocabularies for periods,
materials and object categories; publications; and the cross-cutting tables for
permissions, revisions, activity, notifications and comments.

**Authentication.** Registration, login by e-mail or username, JWT access
tokens, rotating refresh tokens with reuse detection, session listing and
revocation, password change, administrative reset, and account lockout.

**Authorisation.** One policy module combining project membership and
per-record grants, with the approval workflow built in. Milestone 4 replaced
the global role at the top of this with per-module access.

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

**Approval workflow.** Contributors' submissions enter a pending queue, stay
out of public listings until approved, and notify the project's supervisors.
Approving requires both the supervisor level *and* rights on that particular
project — seniority elsewhere does not reach into someone else's excavation.

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

### Milestone 3 — files, media and labels

**Photograph uploads** with automatic thumbnails and EXIF extraction. Camera,
lens, timestamp and GPS fix are read off the file and onto the record, so a
morning's shooting arrives already located and dated. Thumbnails honour the
orientation tag, so portrait photographs are not served on their side.

**Document uploads** — reports, permits, spreadsheets, field notes — validated
against their own leading bytes rather than their extension, with text-based
formats indexed for search.

**3D models**, either linked to where they already live or uploaded as a
lightweight mesh for preview. Recognised viewers get an embeddable URL;
everything else is linked rather than framed.

**Printable QR labels** for artifacts, sites and projects. Scanning one opens
that record, subject to exactly the permissions the record already has.

Three decisions worth calling out:

- **Uploads are validated by content, never by claim.** An image is an image
  only if it decodes as one; a `.pdf` must actually begin `%PDF-`. The extension
  and the declared content type are both attacker-controlled, so neither is
  believed. SVG, HTML and archives are refused outright.
- **Thumbnails carry no metadata.** Stripping it is not tidiness — the platform
  blurs restricted site coordinates, and a thumbnail retaining its GPS tags
  would hand that position straight back.
- **Storage is content-addressed.** Files are named after the SHA-256 of their
  bytes, so a filename can never influence where something is written, and the
  same photograph uploaded twice costs one copy.

### Milestone 4 — foundations for five modules

**Per-module permissions.** A user holds an independent level in each module,
and the grants are additive — the collections manager who runs the museum and
cannot see a single excavation record is now expressible, which it was not
before. Levels are viewer, contributor, editor, supervisor and administrator;
see [Permissions](#permissions).

The global role did not disappear, it narrowed: it now decides who administers
the *platform* (accounts, vocabularies, settings) and nothing else. Migration
`0006` backfills the module access every existing account's role implied, so
nobody can do less after it runs than before.

Two decisions worth calling out:

- **The whole pre-existing suite passes unchanged** against the new model. That
  was the acceptance test for the retrofit: a permission rewrite that quietly
  widens or narrows access is worse than no rewrite, and 118 parametrised
  visibility cases agreeing before and after is the evidence it did neither.
- **Platform powers sit outside the module ladder.** Being administrator of
  every module still cannot create a user account. Modules are about the work;
  accounts and settings are about the institution.

**One storage hierarchy** for every module that holds objects:

```
Institution → Building → Floor → Room → Cabinet → Shelf → Drawer → Box → object
```

Every physical object is filed against a node in that tree, and every change of
place is appended to a register that is never rewritten. The current location
answers *where is it*; the register answers *where was it, when, who moved it
and why* — which is the question that matters when something cannot be found.

Levels may be skipped (a crate on a room floor has no cabinet) and repeated
(finds bags inside a crate), because real stores do both. What is refused is
inversion — a room inside a shelf.

Three decisions worth calling out:

- **The register freezes the paths as they read that day.** Renaming a room
  changes where things *are*; it must not change what the register said on 20
  May. Current location and history are allowed to disagree, and do.
- **A location holding anything cannot be deleted.** Deleting it would leave
  material with no recorded place, the exact state the hierarchy prevents. Mark
  it inactive instead — it keeps its history and stops accepting objects.
- **The legacy free-text locations were not auto-migrated.** Parsing "Field
  house, Room 2, Shelf B" into a tree means guessing which word is the room,
  and a wrong guess writes a wrong location into a heritage register. The old
  text is kept and reported until somebody who knows the building maps it.

### Milestone 5 — GIS, interchange and spatial search

**Map layers** of real PostGIS geometry — trench plans, survey grids,
geophysics outlines — served as literal GeoJSON `FeatureCollection`s, ready to
hand to Leaflet.

**Import and export** in GeoJSON, KML/KMZ and zipped shapefile. An archive
holding several shapefiles reads as one layer, because a shapefile carries one
geometry type and a survey with trenches, finds and a boundary *is* three files.

**Spatial search** across sites, artifacts, contexts and map features at once:
by radius (`/spatial/nearby`), by viewport (`/spatial/bbox`) and inside a
supplied polygon (`/spatial/within`).

The decision this milestone turns on:

- **Coordinate systems are never guessed.** A site grid is almost always in a
  projected system, and a projection bug does not raise anything — the import
  succeeds, the map renders, and the site is in the wrong country until
  somebody visits. So: plausible degrees are accepted, anything else needs an
  explicit `source_srid` and gets reprojected by PostGIS, and a file that
  **contradicts itself** — a `.prj` claiming WGS84 over coordinates that cannot
  be degrees — is refused with a message saying what to send instead.
- **Radii are true metres, not degrees.** A degree of longitude is 111 km at
  the equator and nothing at the pole; a degree-based radius silently changes
  size as the map moves.
- **Restricted sites stay restricted in spatial results.** Coordinates are
  blurred as they are everywhere else, and the *distance* is withheld outright
  rather than rounded — a precise distance from a point the caller chose would
  undo the blurring in one subtraction.

### Milestone 6 — museum collections

**Objects catalogued in your own numbering.** Each collection declares its own
accession pattern; the platform validates against it and continues the
sequence. A number that does not fit — `1974.1a-bis` — is **recorded anyway**,
flagged as legacy, and does not disturb the sequence. That single behaviour
decides whether an existing collection can be migrated at all.

**The excavation link runs one way and only once.** A museum object may point
at the artifact it came from; the excavation record stays as it was written in
the field. Two objects cannot claim the same find. Most of a collection has no
link, because donations and purchases have no excavation record.

**Conservation history, exhibitions and loans.** Treatments record what was
applied and with what, because that is what the next conservator needs.
Exhibition labels are written per exhibition — the same pot reads differently
in a show about trade than one about cooking. Loans are built though unused:
the paperwork becomes urgent with three weeks' notice.

**Environmental monitoring.** Storage locations hold target conditions;
readings hold what was measured. Together they answer "were the conditions
held", which neither answers alone.

**A cataloguing card served as data.** `/forms/layouts/museum_object` returns
tabs, field groups, labels, help text and the value lists behind each dropdown.
The frontend renders that layout rather than carrying its own copy — and the
spreadsheet importer will map columns onto the same description, so the two
cannot disagree about what a record holds.

Two decisions worth calling out:

- **Valuations are withheld from anyone who cannot edit the object**, museum
  viewers included. A valuation on a publicly readable record is an invitation.
- **The museum is permissioned independently.** A collections manager needs no
  excavation access; a field director needs no access to the store's
  valuations. That is what the per-module model was built for.

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
| `GET` | `/users/me/access` | signed in — which modules you can reach |
| `GET`/`PUT`/`DELETE` | `/users/{id}/access[/{module}]` | platform administrator |
| `GET` | `/storage/tree`, `/storage/locations` | anyone with a module that stores things |
| `POST`/`PATCH`/`DELETE` | `/storage/locations[/{id}]` | supervisor and above |
| `GET` | `/storage/locations/{id}/contents` | scoped per object |
| `POST` | `/storage/{kind}/{id}/move` | anyone who may edit the object |
| `GET` | `/storage/{kind}/{id}/location`, `/movements` | anyone who can read it |
| `GET`/`POST` | `/gis/layers[/{id}]` | scoped by permission / contributors |
| `GET`/`POST`/`PATCH`/`DELETE` | `/gis/layers/{id}/features[/{fid}]` | readers / layer editors |
| `POST` | `/gis/import` | contributors — GeoJSON, KML/KMZ or zipped shapefile |
| `GET` | `/gis/layers/{id}/export`, `/gis/export/sites` | anyone who can read it |
| `GET` | `/spatial/nearby`, `/spatial/bbox` | anyone, scoped |
| `POST` | `/spatial/within` | anyone, scoped |
| `GET`/`POST`/`PATCH` | `/museum/collections[/{id}]` | museum viewers / supervisors |
| `GET` | `/museum/collections/{id}/next-number` | museum viewers |
| `GET`/`POST`/`PATCH`/`DELETE` | `/museum/objects[/{id}]` | scoped by museum level |
| `GET` | `/museum/objects/by-number/{number}` | scoped |
| `GET`/`POST` | `/museum/objects/{id}/conservation` | readers / contributors |
| `GET`/`POST` | `/museum/exhibitions[/{id}/items]` | readers / contributors |
| `GET`/`POST` | `/museum/loans[/{id}/items]` | museum viewers / contributors |
| `POST` | `/museum/readings` | museum contributors |
| `GET` | `/museum/locations/{id}/conditions` | museum viewers |
| `GET` | `/forms/layouts/{record_type}` | anyone signed in |
| `POST` | `/photographs`, `/documents`, `/models3d/upload` | contributors on the project |
| `GET` | `/photographs`, `/documents`, `/models3d` | anyone, scoped by permission |
| `GET` | `/photographs/{id}/file`, `/thumbnail?size=` | anyone who can read it |
| `GET` | `/documents/{id}/file`, `/models3d/{id}/file` | anyone who can read it |
| `POST` | `/models3d` | contributors — links a hosted model |
| `PATCH`/`DELETE` | `/photographs/{id}`, `/documents/{id}`, `/models3d/{id}` | editors / owners |
| `GET` | `/{artifacts\|sites\|projects}/{id}/qr.png`, `/label` | anyone who can read it |
| `GET` | `/scan/{kind}/{token}` | anyone, scoped — resolves a scanned label |

Everything is under `/api/v1`. `{kind}` is one of `projects`, `sites`,
`artifacts` or `contexts` — and for revisions and review, also `photographs`
and `documents`.

---

## Permissions

Access is granted **per module**, and the grants are additive. Somebody can run
the museum without seeing a single excavation record, or dig all season without
reaching the institution's budgets:

| | archaeology | museum | inventory | management |
|---|:---:|:---:|:---:|:---:|
| Field director | supervisor | viewer | contributor | — |
| Collections manager | — | administrator | editor | — |
| Finds assistant | contributor | contributor | — | — |
| Communications officer | viewer | viewer | — | — |
| Administrator | *implicit, every module* | | | |

Within each module there are five levels:

| Level | May |
|---|---|
| `viewer` | read |
| `contributor` | create and edit their **own** work; it queues for approval |
| `editor` | edit **anyone's** work in the module; their own needs no approval |
| `supervisor` | approve submissions, start projects, manage teams |
| `administrator` | full control of the module, deletion included |

The contributor/editor line is the one that matters: it separates work that is
checked from work that is trusted.

Creating accounts, editing the controlled vocabularies and changing system
settings are **platform** powers, held only by the global administrator role.
Being administrator of every module does not reach them — running a collection
should not confer the ability to create users.

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

**The dump does not include uploaded files.** The database stores the *path* of
every photograph and document, not its bytes; those live in the `uploads`
volume. Restoring the database alone gives you a complete catalogue in which
every image is a broken link. Copy the volume too:

```bash
# Back up uploaded files alongside the dump
docker run --rm -v archeo_uploads:/data -v "$PWD":/out alpine \
  tar czf /out/uploads-$(date +%F).tar.gz -C /data .

# Restore them
docker run --rm -v archeo_uploads:/data -v "$PWD":/in alpine \
  tar xzf /in/uploads-<date>.tar.gz -C /data
```

Because storage is content-addressed, this archive deduplicates well and a
partial restore is safe: a file either matches its checksum or is absent, never
silently wrong.

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
| `STORAGE_ROOT` | Where uploads are written; a Docker volume by default |
| `MAX_UPLOAD_SIZE_MB` | Per-file ceiling, enforced while reading rather than trusting the declared length |
| `THUMBNAIL_SIZES` | Comma-separated longest edges; one thumbnail per size |
| `FRONTEND_URL` | The address QR labels encode, so a scan opens a page |
| `RUN_MIGRATIONS` / `RUN_SEED` | Both default to `true` and are safe to repeat |

---

## Development

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

pytest                              # 685 tests
pytest --cov=app                    # coverage
ruff check app tests scripts        # lint
alembic revision --autogenerate -m "…"   # after editing models
```

Tests need a PostgreSQL with PostGIS; they create and drop their own database.

---

## Roadmap

The platform is five permissioned modules over one authentication system and
one database — archaeology, museum collections, social media, management, and
office & storage inventory — with a digital archive to follow.

| Milestone | Contents |
|-----------|----------|
| **1 — done** | Backend skeleton, full schema, auth, permissions, Docker, backups |
| **2 — done** | CRUD for projects, sites, artifacts and contexts; revision history; approval workflow; activity feed; search |
| **3 — done** | File uploads, thumbnails, EXIF, documents, 3D models, QR code images |
| **4 — done** | **Foundations for the five-module platform**: per-module permissions, the storage-location hierarchy and movement history |
| **5 — done** | GIS endpoints, GeoJSON/Shapefile/KML import and export, spatial search |
| **6 — done** | Museum module: catalogue, conservation, exhibitions, loans, environmental monitoring, form layouts, spreadsheet import, floor plans |
| **6b — done** | React frontend: sign-in, dashboard, archaeology, museum record card, storage tree, map, search, light/dark |
| **6c — done** | Spreadsheet import with per-column verification; floor plans of the store |
| **7 — done** | Inventory module: equipment, stock with a ledger behind it, calibration, and the excavation kit builder |
| **8 — done** | Management module: funds with a paid/committed/available balance, spending by category, tasks and the calendar |
| 9 | Social media repository; the [data-request system](docs/data-requests.md) and its upload links |
| **10 — done** | The Stratum design applied; the [design brief](docs/design-brief.md) and its appendix |
| 11 | Admin panel; the digital archive module |

Milestone 4 is sequenced ahead of everything else deliberately. The permission
model and the storage hierarchy are load-bearing for every module that follows,
so each one built on the old shape would be rework — and a frontend built on it
would be the most expensive rework available. That is why the interface waited
until milestone 6b, after the permission model and the store were settled: it
was then cheap to build and is now cheap to restyle.

Later: the digital archive module, AI-assisted classification and image tagging,
OCR, satellite and drone imagery, LiDAR, marine survey (MBES and side-scan
sonar), direct publishing through social media APIs, digital signatures, and
offline field collection.

---

## Licence

MIT.
