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

Download the version for your computer:

| Your computer | Download |
|---|---|
| **Windows 10 or 11** | <https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe> |
| **Mac, Apple silicon** (M1/M2/M3/M4) | <https://desktop.docker.com/mac/main/arm64/Docker.dmg> |
| **Mac, Intel** | <https://desktop.docker.com/mac/main/amd64/Docker.dmg> |
| **Linux** | <https://docs.docker.com/desktop/install/linux-install/> |

Not sure which Mac you have? Click the  menu → *About This Mac*. If it says
"Apple M1/M2/M3/M4", choose Apple silicon. If it says "Intel", choose Intel.

Run the installer and accept the defaults. On Windows it may ask to enable
something called WSL and restart your computer — allow it.

**Then open Docker Desktop and leave it running.** It needs to be running
whenever you use the platform. You will see a whale icon in your menu bar (Mac)
or system tray (Windows). Wait until it stops saying "starting".

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

### Sample accounts

The demonstration data includes one account per role, all with the password
`DemoPass!2024`. Sign out and back in as these to see how permissions differ:

| Username | Role | Can do |
|---|---|---|
| `e.marchetti` | researcher | create projects, approve student work |
| `j.okonkwo` | student | add records; they wait for approval |
| `visitor` | visitor | read public records only |

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
