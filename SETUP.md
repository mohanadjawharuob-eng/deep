# Getting the platform running

A complete guide, assuming no programming background. Everything you need to
download is linked below. Expect **20–30 minutes**, most of it waiting.

You do not need to understand any of the code. You are installing one program
(Docker), downloading this project, and running two commands.

---

## What you are installing, in plain terms

This platform is really three programs that talk to each other: a **database**
that stores the records, a **backend** that enforces who may read and change
them, and (from milestone 5) a **website** you click around in.

Installing three programs by hand is fiddly, so they are packaged with
**Docker** — a tool that runs each one in its own sealed box, already
configured. You install Docker once; it handles the rest. Nothing is installed
into your operating system, and removing it later is one command.

---

## Step 1 — Install Docker Desktop

Click the link for **your** computer. Ignore every other row — and if you land
on a page listing Ubuntu, Debian, Fedora, CentOS or Raspberry Pi, you are on
the Linux page by mistake; go back.

### Windows 10 or 11

**Download:**
<https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe>

1. Open your **Downloads** folder and double-click `Docker Desktop Installer.exe`.
2. Leave the checkboxes ticked — one mentions WSL 2, which is required.
3. Click **OK** and wait a few minutes.
4. At "Installation succeeded", click **Close and restart**. Your PC restarts.
5. After restarting, open **Docker Desktop** from the Start menu.
6. Accept the agreement. If it asks you to sign in, look for
   **Continue without signing in** — an account is not needed.
7. Wait for the whale icon at the bottom left to turn green and read
   **Engine running**.

Not sure your Windows is new enough? Press `Windows key + R`, type `winver`,
press Enter. Windows 10 (64-bit) or Windows 11 is fine.

### Mac

Click the  menu → *About This Mac* to see which you have.

- **Apple silicon** (it says M1, M2, M3 or M4):
  <https://desktop.docker.com/mac/main/arm64/Docker.dmg>
- **Intel**: <https://desktop.docker.com/mac/main/amd64/Docker.dmg>

Open the downloaded `.dmg`, drag the Docker icon into Applications, then launch
Docker from Applications. Wait for the whale icon in the menu bar to settle.

### Linux

<https://docs.docker.com/desktop/setup/install/linux/> — pick the page matching
your distribution.

### Either way, before continuing

**Leave Docker Desktop running.** It must be running whenever you use the
platform. If you close it, the platform stops.

---

## Step 2 — Download this project

**Easiest route — download a ZIP:**

1. Open the project page on GitHub in your browser.
2. Click the branch dropdown (it says `main`) and choose
   **`claude/archaeology-platform-backend-xq6xw9`**.
3. Click the green **Code** button → **Download ZIP**.
4. Unzip it. You will get a folder like `deep-claude-archaeology-platform-backend-xq6xw9`.
5. Move that folder somewhere easy to find, such as your Desktop, and rename it
   to `deep` if you like.

**If you have Git installed** and prefer the command line:

```
git clone https://github.com/mohanadjawharuob-eng/deep.git
cd deep
git checkout claude/archaeology-platform-backend-xq6xw9
```

---

## Step 3 — Open a terminal in that folder

A "terminal" is a window where you type commands instead of clicking. You need
it for two commands only.

**On Mac:** open the **Terminal** app (press `⌘ Space`, type `Terminal`,
press Enter). Type `cd ` — that is c, d, then a **space** — then drag the
project folder from Finder onto the Terminal window. It fills in the path.
Press Enter.

**On Windows:** open the project folder in File Explorer, click the address bar
at the top so the path highlights, type `powershell` over it, and press Enter.
A blue window opens already pointing at the folder.

To check you are in the right place, type `ls` (Mac) or `dir` (Windows) and
press Enter. You should see `docker-compose.yml` and a `backend` folder in the
list. If you do not, you are in the wrong folder.

---

## Step 4 — Create your settings

This creates your passwords. Copy the line for your system, paste it into the
terminal, press Enter.

**Mac or Linux:**

```
bash setup.sh
```

**Windows:**

```
powershell -ExecutionPolicy Bypass -File setup.ps1
```

It prints something like:

```
    Address:   http://localhost:8000/docs
    E-mail:    admin@example.org
    Password:  DigySUOyLwM4v4P7x
```

**Write that password down.** You need it in step 6. It is also saved in a file
called `.env` inside the project folder, so it is not lost if you close the
window.

### What that just did, and why

It created a file named `.env` holding three values:

- a **database password**, so only the backend can reach the stored records;
- a **secret key** — a long random string the app uses to sign your login, a
  bit like the watermark on a banknote. Nobody ever types it. It exists so that
  a login token cannot be forged. This is the "secret" that confused you
  earlier, and you never have to see or remember it;
- your **admin password**, which is the one you actually type.

The app refuses to start with placeholder values rather than run insecurely —
so this step is not optional, which is exactly why it is scripted.

---

## Step 5 — Start it

```
docker compose up --build
```

The first run downloads and assembles everything: **several minutes**, and a
great deal of text will scroll past. That is normal. Errors in yellow during
the build are usually harmless.

You are ready when you see a line containing:

```
Application startup complete
```

**Leave this window open.** Closing it stops the platform.

---

## Step 6 — Open it and sign in

In your browser go to:

**<http://localhost:8000/docs>**

You will see a list of every operation the platform can perform. This is the
engine room, not the finished website — the point-and-click interface arrives
in milestone 5. For now this page is how you confirm everything works.

To sign in:

1. Click the **Authorize** button near the top right.
2. **username:** `admin@example.org`
3. **password:** the one from step 4.
4. Click **Authorize**, then **Close**.

### Try it

Find `GET /api/v1/projects` in the list. Click it, click **Try it out**, then
**Execute**. Scroll to *Response body*: you should see the demonstration
excavation, "Tell el-Demo Regional Survey and Excavation".

Also worth a look: `GET /api/v1/sites`, `GET /api/v1/artifacts`, and
`GET /api/v1/search` with `q` set to `bronze`.

### Looking at pictures and labels

The demonstration project comes with three sample photographs and a document.
They are deliberately plain grey-brown cards marked "PLACEHOLDER" rather than
real excavation pictures — the point is to show the machinery working, not to
put invented archaeology in front of you.

1. **See the photographs.** `GET /api/v1/photographs` → *Try it out* →
   *Execute*. Copy the `id` of one of them from the response.
2. **View it.** Open this in a new browser tab, pasting the id in place of
   `<id>`:
   `http://localhost:8000/api/v1/photographs/<id>/thumbnail?size=800`
   A picture should appear. That image did not exist as a file anywhere — it
   was generated from the original when it was stored.
3. **Get a QR label.** `GET /api/v1/artifacts` → *Execute* → copy an artifact's
   `id`, then open:
   `http://localhost:8000/api/v1/artifacts/<id>/qr.png`
   Point your phone's camera at it. It will offer to open a `localhost:5173`
   address — that is the website from milestone 5, which does not exist yet, so
   the link will not load. The code itself is correct; scanning proves it.

Uploading your own photograph is the same idea in reverse: `POST
/api/v1/photographs` → *Try it out* → choose a file, put an artifact's `id`
into the `artifact_id` box, then *Execute*. The response will show the size the
platform read off your image and, if your camera recorded one, where and when
it was taken.

### Sample accounts

The demonstration data includes one account per level, all with the password
`DemoPass!2024`. Sign out and back in as these to see how permissions differ:

| Username | Archaeology level | Can do |
|---|---|---|
| `e.marchetti` | supervisor | create projects, approve other people's work |
| `j.okonkwo` | contributor | add records; they wait for approval |
| `visitor` | viewer | read public records only |

### The map data

The demonstration project includes a trench plan: two trenches and a surveyed
site boundary, drawn around the sample site's real position.

`GET /api/v1/gis/layers` → *Try it out* → *Execute* lists it. Copy the layer's
`id` and open this in a new tab:

`http://localhost:8000/api/v1/gis/layers/<id>/features`

That is **GeoJSON** — the standard format every mapping tool reads. You can
paste it straight into <https://geojson.io> to see the trenches drawn on a map,
which is a fair preview of what milestone 10's interface will show.

You can also download the layer as a file:

- `.../export` — GeoJSON
- `.../export?format=kml` — KML, which opens in Google Earth
- `.../export?format=shapefile` — a zipped shapefile for QGIS or ArcGIS

**Uploading your own map data.** `POST /api/v1/gis/import` accepts GeoJSON, KML
and zipped shapefiles.

One thing to know, because it will look like an error and is not: if your file
is in a **projected coordinate system** — which a total station survey almost
always is, with coordinates like `768000, 3604000` rather than `35.8, 32.5` —
the platform will refuse it and ask for the EPSG code. That refusal is
deliberate. Accepting those numbers as longitude and latitude would put your
site in the wrong country, the map would still draw, and nothing would tell you.
Add `source_srid` (for example `32636` for UTM zone 36N) and it converts them
properly.

### Searching by place

Three ways to ask "what is here", all of which search sites, finds, contexts
and map features together:

- `GET /api/v1/spatial/nearby?lat=34.7324&lon=36.7137&radius_m=2000`
  — everything within 2 km, nearest first.
- `GET /api/v1/spatial/bbox?bbox=36.70,34.72,36.73,34.74`
  — everything inside a rectangle, which is what a map asks as you pan.
- `POST /api/v1/spatial/within` with a polygon — everything inside a shape,
  such as a survey area or a proposed development boundary.

Sites marked as having a restricted location come back deliberately imprecise,
and without a distance, no matter which of these you use.

### Where things are stored

The demonstration data includes a small store, so you can see how the platform
tracks physical objects:

```
Institute of Archaeology
└── Main Store
    ├── Finds Room 203
    │   └── Cabinet 4 → Shelf B → Box 12
    └── Conservation Lab
```

Try it. `GET /api/v1/storage/tree` → *Try it out* → *Execute* shows the whole
store. Then take an artifact's `id` from `GET /api/v1/artifacts` and call:

- `GET /api/v1/storage/artifacts/{id}/location` — where it is **now**
- `GET /api/v1/storage/artifacts/{id}/movements` — everywhere it has **been**

One of the sample finds was accessioned into Box 12 in May and sent to the
Conservation Lab in June, so its history has two steps.

Those are two different questions on purpose. If you rename Finds Room 203
(`PATCH /api/v1/storage/locations/{id}` with `{"name": "Finds Room 500"}`), the
*current location* updates — but the movement register still says the object
was put in Room 203, because that is what happened. A register that rewrote
itself every time a room was renamed would be useless as a record.

To move something: `POST /api/v1/storage/artifacts/{id}/move` with

```json
{ "to_location_id": "<a location id>", "reason": "conservation" }
```

A location holding objects cannot be deleted — you would be left with material
that has no recorded place. Mark it inactive instead.

### The museum collection

The demonstration data includes a small collection, so you can see how objects
are catalogued.

`GET /api/v1/museum/collections` → *Try it out* → *Execute*. You will see one
collection, `ARCH`, with a numbering pattern of `{prefix}.{year}.{seq:04d}` —
which produces numbers like `IOA.2024.0001`.

**Your own numbers.** That pattern is a setting, not a rule the platform
imposes. Change it to whatever your institution already uses:

- `{prefix}.{year}.{seq:04d}` → `IOA.2024.0001`
- `{code}-{yy}/{seq}` → `ARCH-24/7`
- `{seq:06d}` → `000042`

`GET /api/v1/museum/collections/{id}/next-number` shows what the next number
would be without issuing it. Add `?candidate=1974.1a` to check a number you
want to type by hand.

**Old numbers still work.** Catalogue an object with `accession_number` set to
something that does not fit the pattern — `1974.1a-bis`, say — and the platform
records it as given, marks it as a legacy number, and carries on its own
sequence unaffected. Nothing in your existing ledger has to be renumbered to
get into the system. (If you would rather it refused, set `enforce_pattern` on
the collection.)

`GET /api/v1/museum/objects` lists what is there: one object accessioned out of
the excavation — its `artifact_id` points back at the find record — and one
donation from 1974 with no excavation record at all, which is the normal case
for most of a collection.

`GET /api/v1/museum/objects/{id}/conservation` shows the care history: what was
done, when, by whom, and with what materials.

### The cataloguing form

`GET /api/v1/forms/layouts/museum_object` returns the whole cataloguing card as
data — five tabs, fifty-two fields, with labels, help text and the dropdown
options for each. This is what the finished interface will draw, and it is why
the interface will look like the object card a museum cataloguer already knows
rather than a generic web form.

You can read it now to check the fields are the ones you actually use. If
something is missing or misnamed, that is a one-line change in one file, not a
frontend rewrite.

### Who can see which parts of the platform

Access is given **per module** — archaeology, museum, inventory, management,
social media — and the grants stack up independently. Somebody can run the
museum's collection without ever seeing an excavation record, and a field
director can dig all season without reaching the institution's budgets.

Try it: sign in as `admin` and call `GET /api/v1/users/me/access`. You will see
`is_platform_admin: true`, meaning every module. Then look up the student with
`GET /api/v1/users` and call `GET /api/v1/users/{id}/access` with their id —
they hold only `archaeology: contributor`.

To give somebody access to another module, use
`PUT /api/v1/users/{id}/access` with a body like:

```json
{ "module": "museum", "level": "editor" }
```

It takes effect immediately — the person does not have to sign in again.

The five levels, from least to most: **viewer** (read), **contributor** (add
their own work, which waits for approval), **editor** (change anyone's work in
that module, and their own no longer waits), **supervisor** (approve other
people's work, start projects), **administrator** (everything in that module,
including deleting).

Only the *platform* administrator can create user accounts and change system
settings. Being an administrator of every module does not grant that — running
a collection is not the same job as running the institution's accounts.

---

## Everyday use, after the first time

| To do this | Do this |
|---|---|
| **Start it** | Open Docker Desktop, then in the project folder run `docker compose up` |
| **Stop it** | Press `Ctrl + C` in that terminal window |
| **Stop and free memory** | `docker compose down` |
| **Erase all data and start fresh** | `docker compose down -v` — this permanently deletes every record |

Your data survives stopping and restarting. Only `down -v` erases it.

---

## When something goes wrong

**"docker: command not found" / "not recognized"**
Docker Desktop is not installed, or not running. Open it and wait for the whale
icon to settle, then try again.

**"Cannot connect to the Docker daemon"**
Docker Desktop is installed but not running. Open it.

**"password authentication failed for user"**
The database keeps its password from the moment it was first created. If you
re-ran the setup script, your `.env` now holds a *new* password while the
stored database still expects the old one. Wipe it and start again:

```
docker compose down -v
docker compose up
```

`down -v` deletes the database and everything in it. That is fine before you
have entered real records — the demonstration data is recreated automatically —
but not afterwards. To change the password later without losing data, change it
inside PostgreSQL rather than in `.env`.

Note that the database is shared between copies of the project on your machine:
its name is fixed, so running from a second folder reuses the same database, not
a fresh one.

**"port is already allocated"**
Something else on your computer is using port 8000. Open `.env`, find the line
`API_PORT=8000`, change it to `API_PORT=8080`, save, and run
`docker compose up` again. Then use <http://localhost:8080/docs> instead.

**"required variable SECRET_KEY is missing"**
Step 4 did not run, or ran in the wrong folder. Check the project folder
contains a file called `.env`, and re-run step 4 if not. (On Mac, files
starting with a dot are hidden in Finder — press `⌘ Shift .` to show them.)

**The page will not load**
Check the terminal actually says "Application startup complete". If it is still
scrolling, wait. If it stopped with red text, copy that text and send it to me.

**A fix you were told to apply seems to have vanished**
Extracting the ZIP again overwrites your files with whatever that download
contained, so a newer fix applied by hand is undone — and `.env` is deleted with
it, since it is generated rather than downloaded. Either download a fresh ZIP
(it contains every fix) and re-run the setup script, or refresh individual files
in place. Do not re-extract an old ZIP over a working folder.

**Anything else**
Copy the last twenty or so lines from the terminal and send them to me — the
error text says what is wrong far more reliably than a description of it.

---

## Removing it completely

```
docker compose down -v
```

Then delete the project folder, and uninstall Docker Desktop like any other
application. Nothing is left behind elsewhere on your computer.
