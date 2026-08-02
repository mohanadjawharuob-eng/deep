# Letting the platform send e-mail

The platform sends e-mail for three things: resetting a forgotten password,
inviting somebody to a project, and the back-and-forth on a data request. It
works perfectly well without any of this — a machine in a dig house often has
no outbound mail, and that is a supported way to run it. Nothing breaks; the
messages simply are not sent.

This page is for when you do want them sent, using a Gmail account.

**It takes about ten minutes, and the last step tells you whether it worked.**

---

## Why not just the Gmail password

Google stopped letting programs sign in with the password you type into Gmail
several years ago. Instead you generate a separate password, sixteen letters
long, that works for one program and nothing else. It is called an **App
Password**.

Two things follow from that, and both are in your favour:

- If it ever leaks, it lets somebody send mail. It does not let them read your
  inbox, change your password, or get into anything else with your Google
  account.
- You can cancel it at any time from that same page, without changing your
  real password or signing out anywhere.

---

## Before you start

Use an account you are willing to have the platform send from. If this is for
an institution, a dedicated address is much better than a personal one —
`heritage.records@gmail.com` rather than your own. Recipients see the address
in the From line, and replies go back to it.

---

## Step 1 — Turn on two-step verification

Google will not offer App Passwords until this is on. There is no way round
it.

1. Go to **<https://myaccount.google.com/security>**
2. Find **How you sign in to Google**.
3. Click **2-Step Verification**.
4. Follow what it asks — normally it sends a code to your phone.

If it already says **On**, skip to step 2.

---

## Step 2 — Create the App Password

1. Go to **<https://myaccount.google.com/apppasswords>**

   If that page says the option is not available, two-step verification is not
   actually on yet. Go back to step 1.

2. In the box asking for a name, type anything that will remind you later:

   ```
   Stratum
   ```

3. Press **Create**.

4. Google shows you sixteen letters in a yellow box, in four groups of four:

   ```
   abcd efgh ijkl mnop
   ```

5. **Copy it now.** Google will not show it again. If you lose it, delete that
   entry and make a new one — no harm done.

> The spaces are only there to make it readable. You can paste it either way;
> the platform removes them for you.

---

## Step 3 — Put it in the settings file

On the computer that runs the platform, open the project folder and find the
file called **`.env`** — no name, just the extension.

> **If you cannot see it:** Windows hides files that start with a dot. In File
> Explorer, click **View → Show → Hidden items**. On a Mac, press
> **Cmd + Shift + .** in Finder.

> **If there is no `.env` at all:** copy `.env.example` and rename the copy to
> `.env`. That is the normal first step for any setting.

Open it in Notepad (or TextEdit) and add these five lines at the bottom,
putting your own address and the password you just copied:

```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your.address@gmail.com
SMTP_PASSWORD=abcd efgh ijkl mnop
MAIL_FROM_NAME=Stratum
```

Save it and close.

### Three things that trip people up

- **No quotes.** Write `SMTP_PASSWORD=abcdefgh`, not `SMTP_PASSWORD="abcdefgh"`.
- **No spaces around the `=`.** `SMTP_PORT=587`, not `SMTP_PORT = 587`.
- **`SMTP_USERNAME` is the full address**, including `@gmail.com`.

---

## Step 4 — Check it, before trusting it

This is the step worth doing. It takes two seconds and ends with a plain yes
or no.

Open a terminal in the project folder and run:

```
cd backend
python scripts/check_email.py
```

It prints what it is about to use — including how many characters the password
is, but never the password itself — then connects and signs in.

**If it says `Working.`**, you are done. Send yourself a real message to be
completely sure:

```
cd backend
python scripts/check_email.py your.address@gmail.com
```

Check your inbox, and the spam folder the first time.

**If it says `Not working.`**, it also says why. The three you are likely to
see:

| What it says | What it means |
| --- | --- |
| *rejected the username or password* | The password is not an App Password, or it was copied wrong. Make a new one — it costs nothing. |
| *Could not reach smtp.gmail.com:587* | No internet, or this network blocks outbound mail. Some office and university networks do this deliberately. |
| *No SMTP_HOST is set* | The `.env` file was not saved, or was saved somewhere else. Check it is in the project folder and named `.env` exactly — Notepad likes to add `.txt`. |

---

## Step 5 — Restart the platform

Settings are read when it starts, so it will not notice the change until then.

- **Stop Stratum.cmd**, then **Start Stratum.cmd** (or `Share on WiFi.cmd`).

That is everything.

---

## Keeping it safe

The App Password lives in `.env` on that one computer, and nowhere else.

- **`.env` is never committed to the repository.** It is in `.gitignore`, so
  `git push` cannot carry it out by accident. That is deliberate and worth not
  undoing.
- **Do not paste it into a chat, an e-mail, or a screenshot** — including to
  me. I never need it. If you have already, delete that App Password at
  <https://myaccount.google.com/apppasswords> and make another; it takes
  thirty seconds and invalidates the old one immediately.
- **`check_email.py` prints the length, never the password**, so its output is
  safe to copy if you want help reading an error.

---

## If you would rather not use Gmail at all

Any provider works. Only the first three lines change, and the check script
tells you whether you got them right the same way.

| Provider | `SMTP_HOST` | `SMTP_PORT` |
| --- | --- | --- |
| Gmail | `smtp.gmail.com` | 587 |
| Outlook / Microsoft 365 | `smtp.office365.com` | 587 |
| Fastmail | `smtp.fastmail.com` | 587 |
| A university mail server | ask their IT desk | usually 587 |

If a provider tells you to use port **465**, it wants a different kind of
encryption. Set these instead:

```
SMTP_PORT=465
SMTP_SSL=true
SMTP_STARTTLS=false
```

Setting both `SMTP_SSL` and `SMTP_STARTTLS` is refused at startup with an
explanation, rather than left to fail later as an unexplained timeout.
