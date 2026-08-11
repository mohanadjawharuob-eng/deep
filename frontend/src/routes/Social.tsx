/**
 * The social media repository.
 *
 * Two screens: the channels and what has gone out on them, and one post.
 *
 * The design decision worth knowing is where the location warning sits. It is
 * not a badge tucked beside a status — it is a full-width panel at the top of
 * the post, above everything else, naming the image responsible. Publishing a
 * findspot is how looting starts, and a warning somebody has to go looking for
 * is a warning that does not work.
 *
 * It never blocks anything. The approve and publish buttons stay enabled with
 * the warning showing, because sometimes revealing a location is exactly right
 * and a screen that refuses is one people work around.
 */

import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import {
  api,
  type OutreachSummary,
  type Page,
  type SocialAccount,
  type SocialPost,
  type SocialPostDetail,
} from "../lib/api";
import { useAction, useDebounced, useQuery, useSession } from "../lib/hooks";
import {
  Badge,
  Detail,
  DetailGrid,
  Empty,
  ErrorNote,
  Loading,
  PageHeader,
  Pager,
  SearchInput,
  formatDate,
  formatDateTime,
  humanise,
} from "../components/ui";

const PAGE = 50;

/** Post statuses, mapped onto the badge tones the platform already uses. */
const STATUS_TONE: Record<string, string> = {
  draft: "archived",
  needs_approval: "temporary",
  approved: "active",
  scheduled: "on_display",
  published: "active",
  withdrawn: "missing",
};

function StatusBadge({ status }: { status: string }) {
  return <Badge value={STATUS_TONE[status] ?? "archived"} kind="status" label={humanise(status)} />;
}

/* ==========================================================================
 * The repository
 * ======================================================================= */
export function Outreach() {
  const { can } = useSession();
  const [params, setParams] = useSearchParams();
  const [term, setTerm] = useState(params.get("q") ?? "");
  const debounced = useDebounced(term);
  const attention = params.get("attention") === "1";
  const platform = params.get("platform") ?? "";
  const offset = Number(params.get("offset") ?? 0);

  const summary = useQuery<OutreachSummary>(
    (signal) => api.get("/social/summary", undefined, signal),
    [],
  );
  const accounts = useQuery<Page<SocialAccount>>(
    (signal) => api.get("/social/accounts", { limit: 100 }, signal),
    [],
  );
  const posts = useQuery<Page<SocialPost>>(
    (signal) =>
      api.get(
        "/social/posts",
        {
          q: debounced || undefined,
          platform: platform || undefined,
          needs_attention: attention || undefined,
          limit: PAGE,
          offset,
        },
        signal,
      ),
    [debounced, platform, attention, offset],
  );

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("offset");
    setParams(next);
  };

  const warnings = summary.data?.with_location_warnings ?? 0;

  return (
    <>
      <PageHeader
        title="Outreach"
        subtitle="What the institution has said in public"
        actions={
          can("social_media", "contributor") && (
            <Link className="btn btn-primary" to="/social/accounts">
              Channels
            </Link>
          )
        }
      />

      {/* Above everything. A post that would give away where a site is beats
          every other thing on this screen for somebody's attention. */}
      {warnings > 0 && (
        <button
          type="button"
          className="alert alert-warning alert-action"
          onClick={() => setParam("attention", attention ? "" : "1")}
        >
          <div>
            <b>
              {warnings} post{warnings === 1 ? "" : "s"} would give away where something is.
            </b>{" "}
            Usually a photograph still carrying the GPS tag the camera wrote into it.{" "}
            <span className="underline">
              {attention ? "Show everything" : "Show me"}
            </span>
          </div>
        </button>
      )}

      {summary.data && (
        <div className="stat-grid" style={{ marginBottom: "var(--space-5)" }}>
          <div className="stat">
            <span className="stat-label">Published</span>
            <span className="stat-value">{summary.data.published}</span>
          </div>
          <div className="stat">
            <span className="stat-label">Scheduled</span>
            <span className="stat-value">{summary.data.scheduled}</span>
          </div>
          <button
            type="button"
            className="stat"
            onClick={() => setParam("attention", attention ? "" : "1")}
          >
            <span className="stat-label">Awaiting approval</span>
            <span className="stat-value">{summary.data.awaiting_approval}</span>
          </button>
          <div className="stat">
            <span className="stat-label">Channels</span>
            <span className="stat-value">{summary.data.accounts}</span>
          </div>
        </div>
      )}

      <div className="toolbar">
        <SearchInput value={term} onChange={setTerm} placeholder="Title or text…" />
        <select
          className="input input-sm filter-select"
          value={platform}
          onChange={(event) => setParam("platform", event.target.value)}
        >
          <option value="">All channels</option>
          {Object.keys(summary.data?.by_platform ?? {}).map((name) => (
            <option key={name} value={name}>
              {humanise(name)}
            </option>
          ))}
        </select>
        <button
          type="button"
          className={`btn btn-sm${attention ? " btn-primary" : ""}`}
          onClick={() => setParam("attention", attention ? "" : "1")}
        >
          Needs attention
        </button>
      </div>

      {posts.loading ? (
        <Loading />
      ) : posts.error ? (
        <ErrorNote message={posts.error} onRetry={posts.reload} />
      ) : posts.data && posts.data.items.length === 0 ? (
        <Empty title={attention ? "Nothing needs attention" : "Nothing here yet"}>
          {attention
            ? "No post is waiting for approval or carrying a location warning."
            : accounts.data && accounts.data.items.length === 0
              ? "Add a channel first, then draft something on it."
              : "Draft a post on one of the channels."}
        </Empty>
      ) : (
        <section className="card">
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Post</th>
                  <th>Channel</th>
                  <th>Status</th>
                  <th>When</th>
                  <th className="numeric">Engagement</th>
                </tr>
              </thead>
              <tbody>
                {posts.data?.items.map((post) => (
                  <tr key={post.id}>
                    <td>
                      <Link to={`/social/posts/${post.id}`}>{post.title}</Link>
                      {post.location_warning && (
                        <span className="warn-mark" title={post.location_warning}>
                          ⚠ location
                        </span>
                      )}
                    </td>
                    <td className="small muted">
                      {post.platform ? humanise(post.platform) : "—"}
                      {post.handle ? ` · @${post.handle}` : ""}
                    </td>
                    <td>
                      <StatusBadge status={post.status} />
                    </td>
                    <td className="small">
                      {post.published_at
                        ? formatDate(post.published_at)
                        : post.scheduled_for
                          ? `for ${formatDate(post.scheduled_for)}`
                          : "—"}
                    </td>
                    <td className="numeric small">
                      {post.engagement?.interactions != null ? (
                        <>
                          <span className="mono">{post.engagement.interactions}</span>
                          {post.engagement.change != null && post.engagement.change > 0 && (
                            <span className="small muted"> +{post.engagement.change}</span>
                          )}
                        </>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {posts.data && (
            <Pager
              total={posts.data.total}
              limit={PAGE}
              offset={offset}
              onChange={(next) => {
                const params2 = new URLSearchParams(params);
                params2.set("offset", String(next));
                setParams(params2);
              }}
            />
          )}
        </section>
      )}
    </>
  );
}

/* ==========================================================================
 * Channels
 * ======================================================================= */
export function Channels() {
  const { can } = useSession();
  const [adding, setAdding] = useState(false);

  const accounts = useQuery<Page<SocialAccount>>(
    (signal) => api.get("/social/accounts", { limit: 100 }, signal),
    [],
  );

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Outreach", to: "/social" }, { label: "Channels" }]}
        title="Channels"
        subtitle="Where the institution publishes"
        actions={
          can("social_media", "contributor") && (
            <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}>
              Add a channel
            </button>
          )
        }
      />

      {accounts.loading ? (
        <Loading />
      ) : accounts.error ? (
        <ErrorNote message={accounts.error} onRetry={accounts.reload} />
      ) : accounts.data && accounts.data.items.length === 0 ? (
        <Empty title="No channels yet">
          Add the accounts the institution actually posts from. The website counts — it is the
          only channel you control outright, and the only one certain to still be there in ten
          years.
        </Empty>
      ) : (
        <div className="stat-grid">
          {accounts.data?.items.map((account) => (
            <div key={account.id} className="stat" style={{ display: "block" }}>
              <div className="row-tight" style={{ justifyContent: "space-between" }}>
                <span className="stat-label">{humanise(account.platform)}</span>
                {!account.is_active && <Badge value="archived" kind="status" label="Inactive" />}
              </div>
              <div className="strong mono" style={{ marginBottom: 4 }}>
                @{account.handle}
              </div>
              <div className="small muted">
                {account.post_count} post{account.post_count === 1 ? "" : "s"}
                {account.published_count > 0 && ` · ${account.published_count} published`}
                {account.follower_count != null &&
                  ` · ${account.follower_count.toLocaleString()} followers`}
              </div>
              {account.awaiting_approval > 0 && (
                <div className="small" style={{ marginTop: 6 }}>
                  <Badge
                    value="temporary"
                    kind="status"
                    label={`${account.awaiting_approval} awaiting approval`}
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {adding && (
        <ChannelDialog
          onClose={() => setAdding(false)}
          onDone={() => {
            setAdding(false);
            accounts.reload();
          }}
        />
      )}
    </>
  );
}

function ChannelDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [platform, setPlatform] = useState("instagram");
  const [handle, setHandle] = useState("");
  const [displayName, setDisplayName] = useState("");

  const add = useAction(async () => {
    await api.post("/social/accounts", {
      platform,
      handle: handle.trim(),
      display_name: displayName.trim() || null,
    });
    onDone();
  });

  return (
    <div className="modal-scrim" role="dialog" aria-modal="true" aria-label="Add a channel">
      <div className="modal">
        <div className="modal-title">Add a channel</div>
        {add.error && <ErrorNote message={add.error} />}

        <div className="field">
          <label className="field-label" htmlFor="platform">
            Platform
          </label>
          <select
            id="platform"
            className="input"
            value={platform}
            onChange={(event) => setPlatform(event.target.value)}
          >
            {[
              "instagram",
              "facebook",
              "x",
              "youtube",
              "linkedin",
              "threads",
              "bluesky",
              "mastodon",
              "website",
              "newsletter",
              "press",
              "other",
            ].map((name) => (
              <option key={name} value={name}>
                {humanise(name)}
              </option>
            ))}
          </select>
          <p className="field-help">
            Short-form video platforms are deliberately absent: their terms grant broad licences
            over what you upload, which is a decision an institution should make knowingly rather
            than by default.
          </p>
        </div>

        <div className="field">
          <label className="field-label" htmlFor="handle">
            Handle
          </label>
          <input
            id="handle"
            className="input"
            value={handle}
            autoFocus
            placeholder="telldemo_dig"
            onChange={(event) => setHandle(event.target.value)}
          />
          <p className="field-help">Without the @ — it is added back when it is shown.</p>
        </div>

        <div className="field">
          <label className="field-label" htmlFor="display-name">
            Name
          </label>
          <input
            id="display-name"
            className="input"
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
          />
        </div>

        <div className="row-tight" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn" onClick={onClose} disabled={add.running}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={add.running || !handle.trim()}
            onClick={() => void add.run()}
          >
            {add.running ? "Adding…" : "Add"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ==========================================================================
 * One post
 * ======================================================================= */
export function PostScreen() {
  const { postId } = useParams();
  const [publishing, setPublishing] = useState(false);

  const post = useQuery<SocialPostDetail>(
    (signal) => api.get(`/social/posts/${postId}`, undefined, signal),
    [postId],
  );

  const [sendingBack, setSendingBack] = useState(false);

  const approve = useAction(async () => {
    await api.post(`/social/posts/${postId}/approve`, {});
    post.reload();
  });

  if (post.loading) return <Loading rows={8} />;
  if (post.error) return <ErrorNote message={post.error} onRetry={post.reload} />;
  if (!post.data) return null;

  const record = post.data;
  const check = record.location_check;

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Outreach", to: "/social" }, { label: record.title }]}
        title={record.title}
        subtitle={
          record.handle
            ? `${humanise(record.platform ?? "")} · @${record.handle}`
            : undefined
        }
        actions={
          <>
            <StatusBadge status={record.status} />
            {record.can_approve && !["published", "approved", "withdrawn"].includes(record.status) && (
              <button
                type="button"
                className="btn"
                disabled={approve.running}
                onClick={() => void approve.run()}
              >
                {approve.running ? "Approving…" : "Approve"}
              </button>
            )}
            {record.can_approve && record.status !== "published" && (
              <button type="button" className="btn" onClick={() => setSendingBack(true)}>
                Send it back…
              </button>
            )}
            {record.can_edit && record.status !== "published" && (
              <button type="button" className="btn btn-primary" onClick={() => setPublishing(true)}>
                Record as published
              </button>
            )}
            {record.external_url && (
              <a
                className="btn"
                href={record.external_url}
                target="_blank"
                rel="noreferrer noopener"
              >
                Open the post
              </a>
            )}
          </>
        }
      />

      {approve.error && <ErrorNote message={approve.error} />}

      {/* The whole reason this module is in an archaeological platform. Above
          everything, full width, naming the image responsible. */}
      {check && !check.clear && (
        <section className="alert alert-warning" style={{ marginBottom: "var(--space-5)" }}>
          <div>
            <b>This post would give away where something is.</b>
            <ul style={{ margin: "8px 0 0 18px" }}>
              {check.findings.map((finding, index) => (
                <li key={`${finding.kind}-${index}`} className="small">
                  {finding.detail}
                </li>
              ))}
            </ul>
            <p className="small" style={{ margin: "10px 0 0" }}>
              Nothing here is blocked — sometimes this is exactly right. But a geotag in a
              published image is permanent, and stripping it before upload is a one-line fix that
              cannot be made afterwards.
            </p>
          </div>
        </section>
      )}

      <section className="card">
        <div className="card-body">
          {record.body ? (
            <p style={{ whiteSpace: "pre-wrap", marginBottom: "var(--space-4)" }}>{record.body}</p>
          ) : (
            <p className="small muted" style={{ marginBottom: "var(--space-4)" }}>
              No text written yet.
            </p>
          )}
          {record.hashtags && record.hashtags.length > 0 && (
            <div className="row-tight" style={{ flexWrap: "wrap", marginBottom: "var(--space-4)" }}>
              {record.hashtags.map((tag) => (
                <span key={tag} className="badge">
                  #{tag}
                </span>
              ))}
            </div>
          )}
          <DetailGrid>
            <Detail label="Kind" value={humanise(record.kind)} />
            <Detail
              label="Published"
              value={record.published_at ? formatDateTime(record.published_at) : null}
            />
            <Detail
              label="Scheduled"
              value={record.scheduled_for ? formatDateTime(record.scheduled_for) : null}
            />
            <Detail label="About" value={record.subject_label} />
            <Detail label="Project" value={record.project_name} />
            <Detail
              label="Approved"
              value={
                record.approved_by_label
                  ? `${record.approved_by_label}, ${formatDate(record.approved_at)}`
                  : null
              }
            />
          </DetailGrid>
          {record.approval_note && (
            <p className="small muted" style={{ marginTop: "var(--space-4)" }}>
              {record.approval_note}
            </p>
          )}
        </div>
      </section>

      {record.assets.length > 0 && (
        <section className="card">
          <div className="card-header">
            <span className="card-title">Images used</span>
          </div>
          <div className="card-body">
            <div className="asset-strip">
              {record.assets.map((asset) => (
                <figure key={asset.id} className={`asset${asset.has_gps ? " flagged" : ""}`}>
                  <img
                    src={asset.thumbnail_url ?? ""}
                    alt={asset.alt_text ?? asset.filename ?? "Photograph"}
                    loading="lazy"
                  />
                  <figcaption className="small">
                    <span className="mono">{asset.filename}</span>
                    {asset.has_gps && (
                      <span className="warn-mark" title="This file still carries GPS coordinates">
                        ⚠ has GPS
                      </span>
                    )}
                    {asset.credit && <span className="muted"> · {asset.credit}</span>}
                  </figcaption>
                </figure>
              ))}
            </div>
          </div>
        </section>
      )}

      {record.metrics.length > 0 && (
        <section className="card">
          <div className="card-header">
            <span className="card-title">How it has done</span>
            {record.engagement?.change != null && (
              <span className="small muted">
                {record.engagement.change >= 0 ? "+" : ""}
                {record.engagement.change} since the previous reading
              </span>
            )}
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Read on</th>
                  <th className="numeric">Impressions</th>
                  <th className="numeric">Likes</th>
                  <th className="numeric">Comments</th>
                  <th className="numeric">Shares</th>
                </tr>
              </thead>
              <tbody>
                {record.metrics.map((metric) => (
                  <tr key={metric.id}>
                    <td className="small">{formatDate(metric.recorded_at)}</td>
                    {/* An em-dash, not a nought. A figure the platform does
                        not report is not a figure of zero. */}
                    <td className="numeric mono">{metric.impressions ?? "—"}</td>
                    <td className="numeric mono">{metric.likes ?? "—"}</td>
                    <td className="numeric mono">{metric.comments ?? "—"}</td>
                    <td className="numeric mono">{metric.shares ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <ReviewThread post={record} onChanged={() => post.reload()} />

      {sendingBack && (
        <SendBackDialog
          postId={record.id}
          onClose={() => setSendingBack(false)}
          onDone={() => {
            setSendingBack(false);
            post.reload();
          }}
        />
      )}

      {publishing && (
        <PublishDialog
          post={record}
          onClose={() => setPublishing(false)}
          onDone={() => {
            setPublishing(false);
            post.reload();
          }}
        />
      )}
    </>
  );
}

function PublishDialog({
  post,
  onClose,
  onDone,
}: {
  post: SocialPostDetail;
  onClose: () => void;
  onDone: () => void;
}) {
  const [url, setUrl] = useState(post.external_url ?? "");

  const publish = useAction(async () => {
    await api.post(`/social/posts/${post.id}/publish`, { external_url: url.trim() || null });
    onDone();
  });

  const warned = post.location_check && !post.location_check.clear;

  return (
    <div className="modal-scrim" role="dialog" aria-modal="true" aria-label="Record as published">
      <div className="modal">
        <div className="modal-title">Record that this went out</div>
        <p className="small" style={{ margin: "8px 0 14px", color: "var(--text-2)" }}>
          The platform posts nothing itself — it holds no keys to your accounts. Post it where it
          goes, then record it here with the address, so the archive knows what was said and
          where.
        </p>

        {warned && (
          <div className="alert alert-warning" style={{ marginBottom: 14 }}>
            <div className="small">
              This post still carries a location warning. Worth reading it once more before you
              record this as published — a geotag in a published image cannot be taken back.
            </div>
          </div>
        )}

        {publish.error && <ErrorNote message={publish.error} />}

        <div className="field">
          <label className="field-label" htmlFor="url">
            Where it went out
          </label>
          <input
            id="url"
            className="input"
            value={url}
            autoFocus
            placeholder="https://…"
            onChange={(event) => setUrl(event.target.value)}
          />
          <p className="field-help">
            The one thing that cannot be reconstructed later. Optional, but worth the ten seconds.
          </p>
        </div>

        <div className="row-tight" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn" onClick={onClose} disabled={publish.running}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={publish.running}
            onClick={() => void publish.run()}
          >
            {publish.running ? "Recording…" : "Record it"}
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * What colleagues have said about a post that has not gone out.
 *
 * Approving is one bit, and almost no real review is one bit. "The find number
 * is wrong", "wait until the permit is signed", "lovely, but crop the trowel
 * out" are the substance of getting a post right, and with nowhere to put them
 * they are said in a corridor and lost the moment the post goes up.
 *
 * Kept after publication rather than cleared, because why a post says what it
 * says is a question that gets asked later, usually by somebody who was not in
 * the room.
 */
function ReviewThread({
  post,
  onChanged,
}: {
  post: SocialPostDetail;
  onChanged: () => void;
}) {
  const [draft, setDraft] = useState("");

  const add = useAction(async () => {
    await api.post(`/social/posts/${post.id}/notes`, { body: draft.trim() });
    setDraft("");
    onChanged();
  });

  const notes = post.notes_thread ?? [];

  return (
    <section className="card">
      <div className="card-header">
        <span className="card-title">What people have said</span>
        <span className="muted small">{notes.length || ""}</span>
      </div>
      <div className="card-body">
        {notes.length === 0 ? (
          <p className="small muted" style={{ marginTop: 0 }}>
            Nothing yet. A post is easier to fix before it goes out than after.
          </p>
        ) : (
          <ol className="thread">
            {notes.map((note) => (
              <li key={note.id} className={note.decision ? `decision ${note.decision}` : ""}>
                <div className="small muted">
                  {note.author_label ?? "Somebody"}
                  {note.decision === "approved" && " approved this"}
                  {note.decision === "sent_back" && " sent it back"}
                  {" · "}
                  {formatDateTime(note.created_at)}
                </div>
                <div style={{ whiteSpace: "pre-wrap" }}>{note.body}</div>
              </li>
            ))}
          </ol>
        )}

        {add.error && <ErrorNote message={add.error} />}

        <div className="field" style={{ marginTop: 12 }}>
          <textarea
            className="input"
            rows={3}
            value={draft}
            placeholder="The find number is TD-114, not TD-141."
            onChange={(event) => setDraft(event.target.value)}
          />
        </div>
        <button
          type="button"
          className="btn btn-sm"
          disabled={!draft.trim() || add.running}
          onClick={() => void add.run()}
        >
          {add.running ? "Adding…" : "Add a note"}
        </button>
      </div>
    </section>
  );
}

function SendBackDialog({
  postId,
  onClose,
  onDone,
}: {
  postId: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [note, setNote] = useState("");

  const send = useAction(async () => {
    await api.post(`/social/posts/${postId}/send-back`, { note: note.trim() });
    onDone();
  });

  return (
    <div className="modal-scrim" role="dialog" aria-modal="true" aria-label="Send this post back">
      <div className="modal">
        <div className="modal-title">Send it back to be changed</div>
        <p className="small" style={{ margin: "8px 0 14px", color: "var(--text-2)" }}>
          It goes back to a draft and the reason joins the thread, so whoever wrote it can
          see what to do rather than being told no.
        </p>

        {send.error && <ErrorNote message={send.error} />}

        <div className="field">
          <label className="field-label" htmlFor="why">
            What needs changing?
          </label>
          <textarea
            id="why"
            className="input"
            rows={4}
            autoFocus
            value={note}
            placeholder="Wait until the permit is signed."
            onChange={(event) => setNote(event.target.value)}
          />
          <p className="field-help">
            Required — “not yet” with nothing attached is a dead end for whoever wrote it.
          </p>
        </div>

        <div className="row-tight" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn" onClick={onClose} disabled={send.running}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!note.trim() || send.running}
            onClick={() => void send.run()}
          >
            {send.running ? "Sending…" : "Send it back"}
          </button>
        </div>
      </div>
    </div>
  );
}
