# Backend — Archaeological Research & Heritage Management Platform

FastAPI service backed by PostgreSQL + PostGIS. This is the **only** component
that talks to the database; clients reach the data exclusively through this API.

---

## Layout

```
backend/
├── app/
│   ├── main.py               # application, middleware, error handlers
│   ├── core/
│   │   ├── config.py         # settings, from the environment
│   │   ├── security.py       # password hashing, JWT issue/verify
│   │   ├── permissions.py    # the authorisation policy
│   │   └── middleware.py     # request ids, security headers
│   ├── db/
│   │   ├── base.py           # declarative base and mixins
│   │   ├── session.py        # engine and session factory
│   │   └── migrations/       # Alembic
│   ├── models/               # ORM models — one module per domain area
│   ├── schemas/              # Pydantic request/response models
│   ├── services/             # business logic that endpoints call
│   │   ├── records.py        # geometry sync, review status, audit plumbing
│   │   ├── revisions.py      # snapshot / history / restore
│   │   ├── activity.py       # the audit trail
│   │   ├── notifications.py  # inbox entries
│   │   ├── storage.py        # content-addressed file storage
│   │   ├── images.py         # image validation, EXIF, thumbnails
│   │   ├── documents.py      # document validation by magic bytes
│   │   ├── attachments.py    # shared media linking, permissions, serving
│   │   ├── qrcodes.py        # QR images for printed labels
│   │   ├── access.py         # granting and revoking module access
│   │   └── storage_locations.py  # the storage tree and movement register
│   └── api/
│       ├── deps.py           # DI: sessions, current user, role guards
│       └── v1/               # versioned routes
├── scripts/seed.py           # idempotent reference + sample data
├── tests/                    # pytest, against a real PostgreSQL
└── docker/entrypoint.sh      # wait for db → migrate → seed → serve
```

The dependency direction is strictly one way:
`api → services → models → db`. Nothing in `models/` imports from `api/` or
`services/`, which is what keeps the ORM usable from scripts and migrations.

---

## Running locally

Requires Python 3.11+ and a PostgreSQL 14+ with PostGIS 3.

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env          # edit the connection details
alembic upgrade head          # create the schema
python -m scripts.seed --with-samples

uvicorn app.main:app --reload
```

- API: <http://localhost:8000>
- Interactive docs: <http://localhost:8000/docs>
- Alternative docs: <http://localhost:8000/redoc>

For Docker, see the repository root `README.md` — `docker compose up` does all
of the above in one step.

---

## Tests

Tests run against a **real PostgreSQL**, not SQLite: the schema uses PostGIS
geometry, JSONB, arrays and native enums, none of which SQLite models. A
throwaway database (`<your-db>_test`) is created and dropped per session.

```bash
pytest                      # all tests
pytest --cov=app            # with coverage
pytest tests/test_permissions.py -v
TEST_DATABASE_URL=postgresql+psycopg://user:pw@host/db_test pytest
```

The suite lowers the bcrypt work factor (`BCRYPT_ROUNDS=4`, set in
`tests/conftest.py` before settings are read). Production cost is ~0.3 s per
hash and the suite creates hundreds of users; the hashing path is still
exercised, just not at a factor that would make the tests unrunnable.

Worth knowing what each file is for:

| File | Covers |
|------|--------|
| `test_security.py` | password policy, hashing, JWT forgery and expiry |
| `test_auth_api.py` | registration, login, refresh rotation, sessions |
| `test_users_api.py` | directory, profiles, administration |
| `test_permissions.py` | the policy, record by record |
| `test_visibility_sql.py` | that the SQL filter agrees with the policy |
| `test_crud_api.py` | the four record types end to end |
| `test_history_api.py` | versions, restore, review workflow, activity |
| `test_search_api.py` | search results, filters and permission scoping |
| `test_media_api.py` | uploads, EXIF, thumbnails, documents, 3D models, QR labels |
| `test_module_access.py` | per-module permissions, granting, and the module ceiling |
| `test_storage_api.py` | the storage hierarchy, path maintenance and the movement register |

`test_media_api.py` generates its images rather than checking binaries in, so
every property it asserts — dimensions, EXIF, GPS, orientation — is visible in
the test that depends on it. Its QR tests *decode* the generated images and
compare the URL, which is the only assertion that shows a printed label would
actually scan; that needs `opencv-python-headless` from `requirements-dev.txt`,
and those tests skip rather than fail without it.

Uploads during tests go to a temporary directory (`STORAGE_ROOT`, set in
`conftest.py` before settings are read) which is emptied at session start.
Storage is content-addressed, so a file left over from an earlier run would be
deduplicated against and a test asserting bytes were written could pass without
writing anything.

Linting and formatting use ruff:

```bash
ruff check app tests scripts
ruff format app tests scripts
```

---

## Migrations

```bash
alembic upgrade head                              # apply
alembic revision --autogenerate -m "add x to y"   # generate after model edits
alembic downgrade -1                              # step back
alembic check                                     # models vs. migrations in sync?
```

The migrations so far:

| Revision | Purpose |
|----------|---------|
| `0001_extensions` | `postgis`, `pg_trgm`, `unaccent`, `btree_gin` |
| `0002_initial_schema` | every table, index and constraint |
| `0003_activity_project` | denormalised `project_id` on `activity_logs`, so the feed can be read per project |
| `0004_audit_clock_timestamp` | audit timestamps taken at append time rather than transaction start |
| `0005_public_tokens` | `public_token` on `projects` and `sites`, so both can carry a QR label |
| `0006_module_access` | `user_module_access`, replacing the global role as the permission ceiling; backfills every existing account |
| `0007_storage_locations` | the storage hierarchy and the movement register; `artifacts.storage_location_id` |

`0001` is separate because PostGIS must exist before any geometry column is
created. Always read a generated migration before committing it — autogenerate
does not detect renames, and it will happily emit a drop-and-create that loses
data.

`0005` is a worked example of why. Autogenerate emitted a single
`add_column(..., nullable=False)`, which fails on any table that already holds
rows because the default lives in Python, not the database. The committed
version adds the column nullable, backfills a distinct token per existing row,
then applies `NOT NULL` and the unique index.

---

## Files and uploads

Uploaded files never touch the database. `app/services/storage.py` writes them
beneath `STORAGE_ROOT` and everything above it speaks in *relative* paths, so
swapping local disk for S3 means implementing one class rather than editing
every endpoint.

- **Content-addressed.** A stored file is named after the SHA-256 of its bytes.
  The same photograph uploaded twice costs one copy, and no client-supplied
  filename ever influences where something lands — which is the usual way file
  uploads turn into arbitrary writes. The original name is kept on the record
  for display and download, as metadata rather than as a path.
- **Images are validated by decoding them.** Neither the extension nor the
  declared content type is trusted; a file is an image only if Pillow can make
  one of it. SVG is refused — it is a document that can carry script, not a
  raster image. Decompression bombs are capped at 120 megapixels.
- **Documents are validated by their leading bytes**, checked against the
  extension. Archives and HTML are refused outright, and documents are always
  served `Content-Disposition: attachment` — an uploaded file rendered inline
  from this origin would run script as the platform.
- **Thumbnails are generated on upload**, one per size in `THUMBNAIL_SIZES`.
  They honour the EXIF orientation tag, flatten transparency onto white rather
  than producing a black-backed JPEG, and **strip all metadata**, so a thumbnail
  cannot leak the GPS position of a site whose location is restricted.
- **EXIF is extracted but never trusted to be well-formed.** Camera, lens,
  timestamp and GPS fix are pulled onto the record where present; a malformed
  block costs the metadata, not the upload. Coordinates typed by the uploader
  take precedence over the camera's.
- **Deleting a record does not delete the bytes.** Because storage is
  content-addressed, another record may reference the same file. Unlinking is
  safe; collecting unreferenced files is a separate sweep.

3D models are usually *linked* rather than uploaded — photogrammetry output
routinely runs to gigabytes. Recognised viewers (currently Sketchfab) get an
`embed_url` built from the model id alone; everything else is linked and not
framed, because an `<iframe>` pointing at an arbitrary address is a phishing
surface under this platform's name.

---

## Physical storage

One hierarchy serves every module that holds objects — archaeology, museum,
inventory — because an institution has one building. A find, an accessioned
object and a total station all end up on a shelf, and that shelf should not be
described three times in three tables.

```
Institution → Building → Floor → Room → Cabinet → Shelf → Drawer → Box → object
```

The order is enforced only against **inversion**: a child may not sit at a
shallower rung than its parent. Skipping rungs is fine — a crate on a room
floor has no cabinet — and so is repeating one, because finds bags inside a
crate really are boxes inside a box. A hierarchy that refuses to describe the
actual building is one people stop using.

**The path is materialised.** Each node stores its full route from the root
(`/ioa/ms/203/cab-4/b`) plus a readable form, so "everything in Room 203" is an
indexed prefix scan rather than a recursive query on every page load. That
denormalisation has to be maintained: renaming or reparenting a node rewrites
the whole subtree, or a cabinet moved between rooms goes on claiming it is in
the old one. `tests/test_storage_api.py` exists largely to catch that.

**The register is append-only and frozen at the time of the move.** Each row
copies in the paths as they read that day, so renaming a room later does not
rewrite what the register said. Current location and movement history answer
different questions and must be allowed to disagree: "where is it" follows the
rename, "where was it on 20 May" does not.

Two endpoints exist because those questions differ:
`GET /storage/{kind}/{id}/location` for where a thing is now, and
`GET /storage/{kind}/{id}/movements` for everywhere it has been.

Other decisions worth knowing:

- **Deleting a location is refused if it holds anything** — objects or child
  locations. Deleting it would leave material with no recorded place, which is
  the exact state this hierarchy exists to prevent. Mark it inactive instead;
  an inactive location keeps its history and stops accepting new objects.
- **Contents are permission-filtered per object.** The store is not a way
  around record permissions: listing a shelf shows only what the caller could
  already see.
- **Environmental targets live on the location**, because a metals cabinet and
  a textile store want different numbers and a conservator needs the target to
  judge a reading against.
- **Moving an object to where it already is records nothing** and reports a
  conflict, so re-submitting a form cannot manufacture a movement that never
  happened.

### The legacy free-text location

`artifacts.current_location` and `storage_box` predate this hierarchy and hold
things like `"Field house, Room 2, Shelf B"`. They are **not** parsed into the
tree by migration `0007`: deciding which words name a room and which name a
shelf would be guessing, and guessing wrong writes a wrong location into a
heritage register. Both columns are kept, and
`GET /storage/{kind}/{id}/location` reports the free text when nothing
structured has been recorded — an honest "we only know this much" rather than
an empty field. Mapping them is a job for somebody who knows the building.

---

## Labels and QR codes

Projects, sites and artifacts each carry a `public_token`: 32 hexadecimal
characters, stable for the life of the record.

`GET /api/v1/{artifacts|sites|projects}/{id}/qr.png` renders a printable code,
and `/label` returns the same information as JSON for a client laying out its
own label sheet. The encoded URL points at the **frontend** (`/a/<token>`), not
at this API — someone scanning a finds bag wants a page, not JSON — and it is
deliberately short, because fewer characters means a sparser code that survives
being printed small and photographed in bad light at the trench edge.

The token rather than the id is what gets printed, for two reasons: a label
keeps working when the record is renumbered or reidentified, and a token is not
an identifier anyone can iterate over. Scanning enforces the same permissions as
the record's own endpoint, so a leaked label reveals nothing its holder could
not already see.

---

## Authentication

`POST /api/v1/auth/login` returns:

| Token | Lifetime | Stored server-side? |
|-------|----------|---------------------|
| access | 30 min (configurable) | no |
| refresh | 14 days | SHA-256 digest, in `refresh_tokens` |

Send the access token as `Authorization: Bearer <token>`. When it expires,
`POST /api/v1/auth/refresh` exchanges the refresh token for a new pair and
**revokes the presented one**.

Presenting a refresh token that was already rotated revokes every session for
that user. That is deliberate: a replayed token means either the client has a
bug or the token leaked, and the safe reading is the second.

Other properties worth knowing:

- Failed logins are counted; 8 consecutive failures lock the account for 15
  minutes. A successful login or an administrative reset clears the counter.
- Unknown users and wrong passwords return the same status and message, and a
  dummy hash is verified for unknown users so response timing does not reveal
  which addresses are registered.
- Changing a password, deactivating an account, or an administrative reset sets
  `tokens_valid_after`, which invalidates every access token issued earlier —
  no blacklist needed.

---

## Authorisation

Four sources combine, and the **most permissive wins**:

1. **Module access** — a ceiling, per functional area. Rows in
   `user_module_access` say what level a user holds in each module, and the
   absence of a row means no access to that module at all.
2. **Project membership** — the normal path inside a module: joining a team
   confers a level on everything in that project.
3. **Per-record grants** — `record_permissions` rows, for sharing one record
   outside the team.
4. **The global role** — reserved for administering the *platform*: creating
   accounts, editing vocabularies, changing settings. A platform administrator
   holds every module implicitly; no other role says anything about modules.

Ownership and the public flag sit on top: an owner always holds `OWNER` on
their own record, and a public record is readable by anyone including anonymous
visitors — module access does not gate public reading, or anonymous browsing
could not work.

### Modules

Access is **additive** and independent per module, so a collections manager can
run the museum without seeing a single excavation record:

| | archaeology | museum | inventory | management |
|---|:---:|:---:|:---:|:---:|
| Field director | supervisor | viewer | contributor | — |
| Collections manager | — | administrator | editor | — |
| Finds assistant | contributor | contributor | — | — |
| Administrator | *implicit, everywhere* | | | |

Modules are `archaeology`, `museum`, `social_media`, `management`, `inventory`
and `archive`. Only archaeology is built; the rest exist as grantable values so
access can be modelled before the modules land.

### Levels

| Level | May |
|---|---|
| `viewer` | read |
| `contributor` | create and edit their **own** work; it queues for approval |
| `editor` | edit **anyone's** work in the module; their own needs no approval |
| `supervisor` | approve submissions, start projects, manage teams |
| `administrator` | full control of the module, deletion included |

The contributor/editor boundary is the one that matters: it is the difference
between work that is checked and work that is trusted. `requires_approval()`
reads exactly that, which is why promoting someone to editor is what stops
their records queueing — not a change to their job title.

Three capabilities are **platform** capabilities and sit outside this ladder
entirely: `manage_users`, `manage_taxonomy` and `manage_system`. Being
administrator of every module does not reach them, because running a museum
must not confer the ability to create accounts.

### What this replaced

The original single global role (`visitor`/`student`/`researcher`/`admin`) is
still on the user record, and still decides who administers the platform, but
it is no longer the permission ceiling. Migration `0006` backfills the module
access each existing role implied — visitor→viewer, student→contributor,
researcher→supervisor — so nothing anyone could do before, they cannot do
after. The whole pre-existing test suite passes unchanged against the new
model, which is the evidence for that claim.

Records created by contributors start as `pending` and are invisible to readers
until a supervisor on the same project approves them. Supervisors cannot
approve work in projects they are not members of.

Every check lives in `app/core/permissions.py`. Endpoints call it; they never
re-implement it. `tests/test_permissions.py` is the executable specification of
the table above.

### Two expressions of one policy

`can_view`/`can_edit` decide access for a record already in memory. Listings
cannot work that way — loading every row to filter it in Python neither
paginates nor scales — so the same rules also exist as SQL predicates
(`visibility_filter`, `editable_filter`).

That duplication is a standing drift risk, so `tests/test_visibility_sql.py`
asserts the two agree across a matrix of users × records × review states.
Change one without the other and it fails, naming the case.

---

## Version history

`app/services/revisions.py` snapshots a record on creation and again before
every change, so version 1 is always the record as first entered. Snapshots
hold the whole row rather than a diff: restore becomes an assignment instead of
a replay, and an old snapshot stays readable after the schema gains columns.

Three rules are worth knowing:

- **Geometry columns are not versioned.** They are derived from `latitude` and
  `longitude`, which *are* captured, so nothing is lost — and a restore
  re-derives the geometry rather than round-tripping WKB through JSON.
- **Some fields never restore.** `id`, `created_at` and `updated_at` are facts
  about the row. `review_status` is workflow state owned by the approval
  endpoints — restoring it would silently un-approve a record and pull it out of
  public listings. `public_token` backs a QR code printed on a physical label
  and must keep resolving for the life of the object.
- **A restore is itself a version.** The state being replaced is snapshotted
  first, so a restore can be undone, and deleting a record leaves its final
  state in the history — `revisions` deliberately has no foreign key to the
  record.

---

## Data model

28 tables. The core chain is:

```
Project ──< Site ──< ExcavationContext ──< Artifact
                 └──< Photograph / Document / Model3D / GisLayer
```

Design decisions that are not obvious from the schema:

- **UUID primary keys.** Record ids appear in QR codes and public URLs;
  sequential integers would leak collection size and invite enumeration.
- **Signed integer years.** `date_from = -2900` means 2900 BCE. Range queries
  stay plain integer comparisons, and Python's `date` cannot represent BCE.
- **Coordinates stored twice.** `latitude`/`longitude` columns *and* a PostGIS
  `geom`. The plain columns are what forms, CSV exports and imports use; `geom`
  is what spatial queries and the map hit.
- **Bidirectional stratigraphic edges.** "A above B" is stored alongside
  "B below A" so reading a context's relationships never needs a `UNION`.
- **`metadata_json` on the main records.** Every institution has fields nobody
  else wants. JSONB is queryable and indexable, so this is an escape hatch, not
  a dumping ground.
- **Media links are denormalised.** A photograph carries `project_id`,
  `site_id`, `artifact_id` and `context_id`, so the gallery at any level is one
  indexed query rather than a recursive join.
- **Module access is rows, not columns.** One row per user per module they can
  reach. Adding the sixth module is then a new enum value rather than a schema
  change plus an edit everywhere a permission is read.

---

## Security summary

| Concern | Measure |
|---|---|
| Password storage | bcrypt, cost 12, per-password salt |
| Password policy | ≥10 chars, mixed case, digit; 72-byte cap enforced (bcrypt truncates silently past it) |
| Session theft | Refresh rotation with reuse detection |
| Token forgery | HS256 with required claims; `alg: none` and wrong-key tokens rejected |
| Privilege escalation | Role is never read from the request body; authorisation re-reads the user row rather than trusting the token's role claim |
| SQL injection | SQLAlchemy parameter binding throughout; no string-built SQL |
| User enumeration | Identical responses and comparable timing for unknown vs. wrong password |
| Brute force | Per-account lockout after 8 failures |
| Audit | Every write, login and failure appended to `activity_logs` |
| Transport | Security headers on every response; HSTS in production |

Deliberate non-goals at this stage, to be picked up in later milestones: rate
limiting per IP (belongs at the reverse proxy), e-mail verification delivery,
and secret storage in a manager rather than environment variables.
