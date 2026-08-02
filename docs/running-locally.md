# Running the platform on your own computer

Written for someone who does not write software. Every block below includes the
`cd` line — copy the whole block, paste it into the terminal, press Enter.

You need two things running at the same time: the **backend** (the database and
the API) and the **frontend** (the website). They talk to each other.

---

## Once, the first time

### 1. Install Docker Desktop

Download it from <https://www.docker.com/products/docker-desktop/>, install it,
and **open it**. Wait until its whale icon stops animating. Everything below
assumes it is running.

### 2. Install Node.js

Download the **LTS** version from <https://nodejs.org/>. Accept every default.

### 3. Get the code

If you already have the project folder, skip this. Otherwise, in a terminal:

```bash
cd ~
git clone https://github.com/mohanadjawharuob-eng/deep.git
cd deep
git checkout claude/archaeology-platform-backend-xq6xw9
```

### 4. Create the settings file

```bash
cd ~/deep
cp .env.example .env
```

Open `~/deep/.env` in a text editor. For local use the defaults are fine except
for one line:

```
FIRST_ADMIN_PASSWORD=change-this-admin-password
```

**Change it now, to something you will remember.** This is the password you will
sign in with. It is read only the first time the database is created, so
changing it later has no effect — see the troubleshooting note at the bottom if
you need to.

`.env` is never committed to the repository, so what you write there stays on
your machine.

---

## The short way: one button

After the first-time setup below, you never need to remember any of these
commands again.

**Windows** — double-click **`Start Stratum.cmd`** in the project folder.

**macOS or Linux** — run `bash start.sh` in the project folder.

It opens Docker Desktop if it is closed and waits for it, fetches any newer
version of the project, starts the backend with `--build` so you can never end
up running last week's code, waits until the backend actually answers, starts
the website, and opens your browser at it.

Leave the window open while you use the platform. Closing it stops the
website; the backend keeps running in Docker. **`Stop Stratum.cmd`** (or
`bash stop.sh`) shuts that down too. Neither deletes any data.

If you have edited a file in the project folder, the launcher says so and does
**not** update — your work is never overwritten.

### Letting colleagues use it too

**`Share on WiFi.cmd`** (or `bash share.sh`) instead of the start button.

It prints an address like `http://192.168.1.50`. Anyone on the same WiFi types
that into a browser — **they install nothing at all**, and everyone shares one
database, so a record catalogued on one machine is on every other one as soon
as it refreshes.

Two things follow from that:

- **This computer must stay on and awake.** When it sleeps, everyone else is
  disconnected. Worth checking the power settings.
- **Give each person their own account.** The platform records who changed
  what, and that is worth nothing if everybody signs in as you.

See [Letting other people use it](deploying.md) for the detail.

### Put it on the desktop

Right-click `Start Stratum.cmd` → **Show more options** → **Send to** →
**Desktop (create shortcut)**. Then it really is one double-click.

---

## Getting a newer version

*(The launcher above does this for you. This section is for doing it by hand.)*

**You never need to download the project again.** `git pull` brings the changes
into the folder you already have.

```bash
cd ~/deep
git pull origin claude/archaeology-platform-backend-xq6xw9
```

Then start it with `--build` added, **once**, after any pull:

```bash
cd ~/deep
docker compose up --build
```

`--build` rebuilds the backend image. Without it, Docker keeps running the
image it built the first time, so new features that need a new Python package
— the spreadsheet importer needs one — fail with a message about support not
being installed on the server.

Database changes are applied for you when the container starts; there is no
migration command to run by hand.

Your data is kept. Nothing above deletes it.

---

## Every time you want to use it

### Step 1 — start the backend

```bash
cd ~/deep
docker compose up
```

*(Add `--build` if you have just pulled new code — see the section above.)*

Leave this window open. It will print a lot; that is normal. Wait until you see
a line containing `Application startup complete`.

**Check it worked.** Open <http://localhost:8000/docs> in your browser. You
should see a page listing every API operation. If you do, the backend is up.

### Step 2 — put the sample data in

**Open a second terminal window** (leave the first one running).

```bash
cd ~/deep
docker compose exec api python -m scripts.seed --with-samples
```

This creates a demonstration excavation, a museum collection, a store with
objects filed in it, photographs and a map layer. It is safe to run more than
once — it only fills in what is missing.

### Step 3 — start the website

Still in the second terminal:

```bash
cd ~/deep/frontend
npm install
npm run dev
```

The first `npm install` takes a minute; after that it is instant. When it
prints `Local: http://localhost:5173/`, open that address.

### Step 4 — sign in

| Account | Password | What they see |
|---|---|---|
| `admin@example.org` | the `FIRST_ADMIN_PASSWORD` you set in `.env` | Everything — all modules |
| `researcher@example.org` | `DemoPass!2024` | Archaeology only, as a supervisor |
| `student@example.org` | `DemoPass!2024` | Archaeology as a contributor; entries need approval |

Signing in as two different accounts is the quickest way to see the permission
system working: the researcher has **no Museum section in the sidebar at all**,
because they hold no access to that module. That is deliberate.

---

## What to look at, in order

Sign in as **`admin@example.org`** for the full tour.

1. **Dashboard.** Counts, recent projects, and an activity feed. Click a count.

2. **Museum → Catalogue.** Two objects. Note `1974.1a` is marked **legacy** — it
   does not match the collection's numbering pattern, and the platform records
   that rather than refusing or hiding it.

3. **Open an object.** This is the screen to look at hardest — it is the one the
   design work is really about.
   - Five tabs across the top.
   - `‹ 1 / 2 ›` in the header is the **record counter**: it walks the search you
     made, not the whole database. Go back to the catalogue, filter by a
     collection, open a record, and the counter follows that filtered set.
   - Press **Edit**. Fields become inputs. Dropdowns are filled from the database
     — periods, materials, categories. A banner counts your unsaved changes.
     Nothing is written until you press **Save**.
   - The accession number and collection stay locked while editing. Renumbering
     an object is a separate, audited operation, not a field edit.
   - Below the fields are the **portals**: conservation history, location
     history, photographs, exhibitions.

4. **Museum → Collections.** Open one. It shows the numbering pattern, the next
   number that will be issued, and whether the pattern is enforced.

5. **New object.** Museum → Catalogue → **New object**. Pick a collection and the
   platform tells you the number the object will receive before you create it.

6. **Storage.** The tree: Institute of Archaeology → Main Store → Finds Room 203
   → Cabinet 4 → Shelf B → Box 12. Click **Box 12** — three finds are filed
   there. Click a parent instead and you get everything beneath it.

7. **Map.** Sites and finds around the demonstration site in Syria. Pan and the
   map reloads what is on screen. Zoom out far and it stops loading rather than
   asking for the world.

8. **Search.** Press <kbd>/</kbd> anywhere. Type `tell`. Results are grouped by
   type with counts.

9. **The theme.** The sun/moon button in the top bar cycles light → system →
   dark. Both themes are meant to be finished, not one plus an inversion.

10. **Archaeology → Projects → Tell el-Demo.** Sites, contexts, finds,
    photographs.

11. **Museum → Import.** The spreadsheet importer, and the screen you asked
    for. Drag a `.xlsx` or `.csv` onto the box and press **Read the file** —
    nothing is written to the catalogue by that.

    The next screen is the point: every column of your file, the values it
    actually contains, and a dropdown saying what it fills. Correct anything
    the platform guessed wrongly; set a column to **Do not import** to leave
    it out on purpose. Choose the collection at the top — almost no
    spreadsheet names one.

    Then **Check every row**. It reports what would happen, failures first,
    numbered as the rows are numbered in Excel. Only **Create** writes
    anything, and the run can be undone afterwards.

    There is a test file at `backend/tests/` if you want one, but the point is
    to try it with **your own register**. It will refuse things — a cell with
    two measurements in it, a date that could be day/month or month/day — and
    the refusals are the feature. Nothing is guessed at.

12. **Store → Floor plans.** Pick a location in the storage tree first
    (**Store → Locations → Finds Room 203**), then press **Show on the plan**
    or **Draw a plan**.

    Press **Edit plan** and drag on the grid to draw. Four tools: **Case** for
    a cabinet or shelf run, **Wall** for scenery so the room is recognisable,
    **Pin** for something standing on the floor, **Text** for a note.

    The important step is on the right: with a shape selected, set **This
    shape is** to a place in the store. That is what makes the plan useful —
    it then shows what that place holds, and **keeps showing the right thing
    when objects move**, because the plan stores no inventory of its own. An
    empty case is drawn hollow and dashed.

    If your museum already has a floor plan as an image, that is the normal
    way in. In **Edit plan** there is an **Upload a plan** button on the right;
    the drawing then goes on top of your image. Replacing it later with a
    better scan is safe — shapes are stored as fractions of the plan, not
    pixels, so nothing moves.

---

## Making notes for changes

You asked to prepare a draft of edits. The most useful form is a list where each
line says **where** and **what**, like:

> *Museum record card, Identification tab* — "Former no." should sit next to
> "Accession no.", not below it.
>
> *Catalogue list* — add a column for storage location.
>
> *Storage tree* — box icons are hard to tell apart at depth.
>
> *Import* — I want a column mapped to two fields at once.

Screenshots with arrows drawn on them are just as good. Anything that names a
screen and a change can be acted on directly.

---

## Stopping

In each terminal window press <kbd>Ctrl</kbd>+<kbd>C</kbd>. To shut the database
down properly:

```bash
cd ~/deep
docker compose down
```

Your data stays. `docker compose down -v` deletes it — only use that when you
want to start clean.

---

## If something goes wrong

**The website loads but says "Something went wrong" everywhere.** The backend is
not running. Check the first terminal, and check <http://localhost:8000/docs>.

**"port is already allocated".** Something else is using port 8000. Change
`API_PORT` in `.env` to `8001`, then start the website with the matching
address:

```bash
cd ~/deep/frontend
API_URL=http://localhost:8001 npm run dev
```

**Sign-in says "Incorrect credentials".** The administrator password is the one
that was in `.env` **at the moment the database was first created**. Editing
`.env` afterwards does not change it. To start clean — this deletes all your
data:

```bash
cd ~/deep
docker compose down -v
docker compose up
```

then re-run the seed from Step 2.

**`npm: command not found`.** Node.js is not installed, or the terminal was open
before you installed it. Close the terminal, open a new one.

**The map is blank.** It needs internet access for its background tiles. The
records themselves come from your own machine.
