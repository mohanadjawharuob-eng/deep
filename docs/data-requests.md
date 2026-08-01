# The data request system — design notes

Not built yet. This records the decision so it is not re-argued later, and so
whoever implements it knows why the obvious options were rejected.

## What it has to do

Every record carries a **Request Data** button. Pressing it emails somebody:

> Please upload the photographs for Artifact A-102.

They follow a link, upload the files, and the files attach themselves to that
record. The requester is notified when they arrive.

## The decision: email carries the request, the platform carries the files

Email sends the *ask* and the notification. The bytes go straight to this
platform through a signed, expiring, single-purpose upload link.

### Why not email the files

Gmail attachments cap at **25 MB**. A single RAW frame is 30–80 MB; a
photogrammetry set is gigabytes; a LiDAR scan more. Email can carry a permit
scan and almost nothing else this platform deals in.

### Why not WeTransfer

Three reasons, any one sufficient:

1. **Links expire** — seven days on the free tier. A heritage archive whose
   records point at expired transfers has holes in it, and the holes appear
   silently, a week after everything looked fine.
2. **It is a transfer service, not storage.** The file was never *in* the
   archive; a copy passed near it.
3. **No usable programmatic upload API.** The public developer API was sunset,
   so the platform could not drive it even if the first two did not apply.

The 2 GB free ceiling is the least of the problems.

### Why not "link to my Google Drive"

Same failure mode, slower: the link rots when the sender reorganises their
drive, leaves the institution, or loses access. If a Drive or OneDrive link is
supplied, the platform should **fetch the file and store it**, not record the
link and hope.

## Shape of the implementation

**Upload tokens.** A signed token carrying the target record, the requested
kind of material, an expiry, and a single-use marker. Signed with the existing
`SECRET_KEY` machinery, so no new secret. The token grants permission to *write
one thing to one record* — nothing else, no session, no read access.

**Resumable upload.** Multi-gigabyte uploads over field internet drop. Chunked
upload against a session id, so a resumed upload continues rather than
restarting. Everything then goes through the existing validation — decoded if
an image, magic-byte checked if a document — because a file arriving by
invitation is no more trustworthy than one arriving by form.

**Delivery.** SMTP, configured per institution:

| Setting | Notes |
|---|---|
| `SMTP_HOST` | `smtp.gmail.com` for Gmail |
| `SMTP_PORT` | 587 with STARTTLS |
| `SMTP_USERNAME` | the sending address |
| `SMTP_PASSWORD` | a Gmail **App Password**, not the account password |
| `SMTP_FROM` | what recipients see |

Gmail requires 2FA enabled before App Passwords can be created, and sends
roughly 500 messages a day on a free account, 2000 on Workspace. That is far
above what request emails need.

The password belongs in `.env` on the server. It is a credential: never in the
repository, never in a chat window, never in a screenshot.

Microsoft 365 and institutional servers are the same SMTP path with different
hosts. OAuth2 for Gmail is a later refinement — an App Password gets it working
without an OAuth consent screen, and swapping the transport later touches one
module.

## What this buys

No third-party size ceiling. No expiry the platform did not choose. No
dependency on a company that may sunset an API. The file lands in the archive
attached to the record it belongs to, checksummed and deduplicated like every
other upload — which is the whole point of asking for it.
