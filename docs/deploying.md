# Letting other people use it

Written for someone who does not write software.

---

## Why nobody else can see it at the moment

When you open `http://localhost:5173`, **localhost means "this computer"**. It
is not a name anybody else can type. A colleague at the next desk typing it
would reach their own machine and find nothing.

That is not a limitation to work around — it is what you want while you are the
only one using it. Everything so far has been running in *development* mode:

- The website is served by a tool that rebuilds it every time you save a file.
  Convenient for changing things, several times slower than it needs to be, and
  it announces itself as not for real use.
- There is no encryption, so anything typed — including passwords — crosses the
  network as plain text.
- Nothing restarts if the machine reboots.

Making it available to other people means changing all three. The good news is
that it is one command, and the platform was built expecting it.

---

## The three ways, in order of commitment

### 1. One computer in the office

Everyone connects to **your** machine across the office network. Free, needs no
internet, and takes about a minute to set up.

Good for: a small team in one building, trying it properly before committing.

Bad for: anybody working from home, and the machine has to stay on.

### 2. A server the institution already owns

The same thing, on a machine that lives in a cupboard and never gets closed.

Good for: an institution with its own IT, or a rule that data must not leave
the building — which is common for archaeological data and worth checking
before choosing option 3.

### 3. A rented server on the internet

Reachable from anywhere, with a real address like
`stratum.your-institute.org` and a padlock in the browser.

Good for: field teams, several sites, anybody working from home.

Costs: roughly €5–20 a month for a small virtual server, plus a domain name at
around €12 a year.

---

## Option 1 — one computer in the office

### The one-click way

**Windows** — open `Stratum.cmd` and press **Share on the office network**.
**macOS or Linux** — run `bash share.sh`.

It works out this machine's address on the network, records it in the
settings, builds the interface properly, starts everything, and prints the
address in large letters for you to pass on. Nobody else installs anything.

That is the whole procedure. The rest of this section is the same thing by
hand, for when you want to know what it did.

### By hand

**On the machine that will host it:**

```bash
cd ~/deep
```

Open `.env` and set these two lines:

```
SITE_ADDRESS=:80
PUBLIC_URL=http://192.168.1.50
```

Replace `192.168.1.50` with that machine's own address on the network. To find
it: on Windows run `ipconfig` and look for **IPv4 Address**; on macOS it is in
System Settings → Network.

Then:

```bash
cd ~/deep
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

**Everyone else** opens `http://192.168.1.50` in a browser. No installation, no
setup — just the address.

Windows will probably ask whether to allow Docker through the firewall the
first time. Say yes, for **private networks**.

### What changed

The website is now built once into plain files and served properly, rather than
rebuilt on every keystroke. It is several times faster to load. The backend is
no longer reachable directly at all — everything goes through one door.

---

## Option 3 — on the internet

You need a virtual server (Hetzner, DigitalOcean, OVH and others all do this)
running Ubuntu, and a domain name pointed at its address.

**On the server:**

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-plugin git
git clone https://github.com/mohanadjawharuob-eng/deep.git
cd deep
bash setup.sh
```

Then open `.env` and set:

```
SITE_ADDRESS=stratum.your-institute.org
PUBLIC_URL=https://stratum.your-institute.org
```

```bash
cd ~/deep
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

**HTTPS is automatic.** The certificate is obtained on first start and renewed
for ever after, with no command to run and nothing to remember in ninety days.
For it to work, the domain must already point at the server and ports 80 and
443 must be open.

### Before you put real data on it

- **Change the administrator password** from whatever `setup.sh` generated.
  Sign in and use the account menu.
- **Check the backups are running.** The `backup` container writes a dump every
  night, but a backup that has never been restored is a hope, not a backup —
  try restoring one onto your own machine once.
- **Decide where the data may live.** Some funders and ministries require
  excavation data to stay in the country of origin. That decides which company
  you rent from, and it is much easier to answer before the data is on it.

---

## Putting the files on a bigger disk

By default Docker keeps everything in its own area, which on Windows is a
virtual disk inside WSL that sits on `C:` however much you would rather it did
not. A single season of drone imagery is enough to make that the wrong place.

**What moves:** the original uploaded files — photographs, drone imagery, 3D
models, documents, imported spreadsheets, floor plan scans — and the nightly
backups. These are stored exactly as they were uploaded; nothing is re-encoded
or thrown away.

**What does not:** the database itself. PostgreSQL wants a real filesystem with
real locking, and a bind mount from Windows into a Linux container is neither —
it is markedly slower and has been known to corrupt a database under load. The
database is small anyway: fifty thousand catalogued objects is a few hundred
megabytes, against several hundred gigabytes of photographs. It is the
photographs that need the room.

### Setting it up

Make the folder first — Docker will create it otherwise, but owned by root,
and then Explorer will not let you open it without a fight.

Then in `.env`:

```
DATA_ROOT=D:/stratum-data
BACKUP_ROOT=E:/stratum-backups
```

Forward slashes, even on Windows. `BACKUP_ROOT` is optional and worth setting
— see [below](#the-part-worth-arguing-with). Then add the file to the command:

```bash
cd ~/deep
docker compose -f docker-compose.yml -f docker-compose.storage.yml up -d
```

Sharing on the network as well? All three stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.storage.yml up -d --build
```

### Moving files that are already there

If you have already uploaded things, they are in Docker's area and the command
above will start from an empty folder. Copy them across first:

```bash
cd ~/deep
docker compose down
docker run --rm -v archeo_uploads:/from -v D:/stratum-data/uploads:/to alpine sh -c "cp -a /from/. /to/"
docker run --rm -v archeo_backups:/from -v D:/stratum-data/backups:/to alpine sh -c "cp -a /from/. /to/"
```

Then start with `-f docker-compose.storage.yml` added. Check a photograph
loads in the platform before deleting anything — `docker volume rm
archeo_uploads` is not reversible.

### Everyone's uploads land here too

There is one server, so this is where *everybody's* files go — not just yours.
A colleague uploading a season of photographs fills this disk, not theirs.

That is usually what you want: one copy, backed up together, findable by
everyone. It does mean the free space on this machine is the platform's real
limit, and a terabyte is a season or two of drone imagery rather than a
lifetime. Worth watching.

---

## The part worth arguing with

Setting aside a terabyte on the laptop and pointing the platform at it is the
right *shape*. Docker's own area is the wrong place for excavation
photographs, and one shared copy beats five people each keeping their own.
Three things about it deserve saying plainly, because they are the ones that
bite later rather than now.

### One disk holding the only copy is not an archive

This is the important one. Before, a dead laptop cost you a laptop. After, the
laptop *is* the archive — for the whole team, including the photographs of
contexts that no longer exist because they were excavated. Excavation records
are not reproducible. You cannot go back and re-photograph a removed layer.

So: a terabyte of storage is a place to *work from*, not a place to *keep*
things. Something has to hold a second copy.

- **If the terabyte is a partition of the laptop's own drive**, it buys
  capacity and no safety at all. Same disk, same failure, same theft, same
  spilled coffee. This is worth being clear-eyed about — partitioning feels
  like separation and is not.
- **If it is an external drive**, capacity is solved and the platform now
  breaks whenever it is unplugged. Docker on Windows handles a vanished bind
  mount badly. Leave it plugged in, or expect to restart the platform after
  every disconnection.
- **Either way, a copy needs to leave the building.** A second external drive
  swapped monthly and kept somewhere else is unglamorous and works. Cloud sync
  on the uploads folder also works, and is easier to forget to check.

### Backups on the same disk are copies, not backups

Unset, `BACKUP_ROOT` puts the nightly database dumps beside the photographs
they describe. That covers "somebody deleted a record". It does not cover the
disk failing, which takes the photographs and the catalogue describing them in
the same instant — and a photograph with no record of which context it came
from is not much better than a lost one.

Set `BACKUP_ROOT` to any second disk. The dumps are small: they hold the
records, not the images, so a month of them is a few gigabytes.

### A terabyte is two or three seasons, not a career

Rough arithmetic, because "a terabyte" sounds larger than it behaves here:

| | Typical |
| --- | --- |
| One photogrammetry survey of one trench | 20–60 GB of raw frames |
| A season's finds photography, DSLR, RAW + JPEG | 40–100 GB |
| A processed 3D model, with its textures | 1–5 GB each |
| The database, at 50,000 catalogued objects | a few hundred MB |

Two or three field seasons with regular drone flights will fill it. That is
fine — it just means the plan needs a next step before it happens rather than
after, because a full disk stops uploads working with no warning.

Check the free space when a season ends. It is a better moment than the middle
of one.

---

## How people get accounts

Two ways, and the difference matters.

**They sign themselves up.** Anybody who can reach the site can create an
account at the sign-in screen. A new account arrives with **no access to
anything** — they can sign in, and see nothing, until somebody grants them a
module.

**You create it for them.** As an administrator: the account menu → users. You
set the modules at the same time.

Either way the second step is the same, and it is the one that matters.

### What a person can see

Access is granted **per module**, and the modules are independent:

| Level | What it means inside one module |
|---|---|
| Viewer | Reads. Changes nothing. |
| Contributor | Creates and edits their own work; it waits for approval. |
| Editor | Edits anyone's work. Their own needs no approval. |
| Supervisor | Approves other people's work, starts projects, imports. |
| Administrator | Full control of that module, deletion included. |

A conservator can be an **editor in the museum** and hold **nothing at all in
archaeology** — no excavation records, and no Archaeology section in their
sidebar, because the platform hides what a person cannot reach rather than
showing them a door that says no.

This is why the demonstration `researcher@example.org` account has no Museum
section: it is not a bug to fix, it is the whole point.

---

## Keeping it running

**Updating** to a newer version:

```bash
cd ~/deep
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Database changes are applied automatically when it starts. Nobody needs to be
logged out first, though anyone mid-edit will need to press Save again.

**When it will not start.** Docker only ever says `container archeo-api is
unhealthy`, which is a symptom and never a reason. The reason is in the
backend's own log, and there is a button for it:

> **Open `Stratum.cmd` and press “Show the log”** (Windows), or run `bash logs.sh`
> (macOS and Linux).

It changes nothing, and it writes the same text to `stratum-log.txt` next to
the launcher so it can be attached to a message. It reads no passwords — the
settings file is not opened by it at all. Look for a block headed
`STRATUM DID NOT START`, then for any line with `ERROR` in it, then at the
last few lines of the api log.

**Watching it as it runs:**

```bash
cd ~/deep
docker compose logs -f api
```

**Stopping it** (your data is kept):

```bash
cd ~/deep
docker compose -f docker-compose.yml -f docker-compose.prod.yml down
```

---

## Which one should you choose

If you are still deciding whether this is the right platform: **option 1**. It
takes a minute, costs nothing, and two colleagues using it for a week will tell
you more than any amount of further building.

Move to option 3 when somebody needs it from outside the building — which for
an excavation usually means the first field season.
