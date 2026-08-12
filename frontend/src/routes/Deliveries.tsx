/**
 * Sending files to somebody who does not have an account.
 *
 * The commonest request an institution gets is *send me the photographs of the
 * jar and the finds register*, and the person asking is a ministry officer, a
 * visiting specialist, a journalist. They will not be given an account and
 * should not need one.
 *
 * Two screens. **Send** builds a bundle from whatever was chosen elsewhere —
 * the media library, the sheet room — writes it to the assigned disk under
 * readable folder names, and mails a link. **Sent** is the record of what went
 * to whom, which is the thing an institution needs years later when a rights
 * query arrives.
 *
 * The screen is careful about one promise it cannot keep. Nothing here puts a
 * folder on somebody else's computer; no web platform can. What it does is put
 * the folder on the disk the institution assigned and say where it is — and on
 * the machine the platform runs on, that folder *is* local, which is the part
 * that was actually wanted. The path is shown, in monospace, as a fact rather
 * than as a link.
 */

import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api, type Page } from "../lib/api";
import { useAction, useQuery, useSession } from "../lib/hooks";
import {
  Badge,
  Empty,
  ErrorNote,
  Loading,
  PageHeader,
  formatDate,
  formatDateTime,
} from "../components/ui";

type Delivery = {
  id: string;
  title: string;
  note?: string | null;
  to_name: string;
  to_email: string;
  status: string;
  file_count: number;
  size_bytes: number;
  missing?: string[] | null;
  expires_at?: string | null;
  collected_at?: string | null;
  collected_count: number;
  notified: boolean;
  created_at: string;
  folder_on_disk?: string | null;
  owner_label?: string | null;
  collect_url?: string | null;
};

const TONE: Record<string, string> = {
  preparing: "temporary",
  ready: "active",
  collected: "on_display",
  expired: "archived",
  failed: "missing",
};

function size(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** Ids handed over in the URL by whichever screen the files were chosen on. */
function idsFrom(value: string | null): string[] {
  return (value ?? "").split(",").map((item) => item.trim()).filter(Boolean);
}

export function SendOutgoing() {
  const { can } = useSession();
  const [params] = useSearchParams();

  const photographs = idsFrom(params.get("photographs"));
  const documents = idsFrom(params.get("documents"));
  const sheets = idsFrom(params.get("sheets"));
  const total = photographs.length + documents.length + sheets.length;

  const [title, setTitle] = useState("");
  const [toName, setToName] = useState("");
  const [toEmail, setToEmail] = useState("");
  const [note, setNote] = useState("");
  const [days, setDays] = useState("30");
  const [made, setMade] = useState<Delivery | null>(null);

  const send = useAction(async () => {
    const created = await api.post<Delivery>("/deliveries", {
      title: title.trim(),
      to_name: toName.trim(),
      to_email: toEmail.trim(),
      note: note.trim() || null,
      photograph_ids: photographs,
      document_ids: documents,
      sheet_ids: sheets,
      expires_in_days: Number(days) || 30,
    });
    setMade(created);
  });

  if (!can("archaeology", "contributor") && !can("museum", "contributor")) {
    return (
      <Empty title="Sending files out is not yours to do">
        It needs contributor access, because a link that needs no account is the one
        way material leaves the institution without anybody signing in.
      </Empty>
    );
  }

  if (made) {
    return (
      <>
        <PageHeader
          breadcrumb={[{ label: "Sent", to: "/sent" }, { label: made.title }]}
          title="Ready to collect"
          subtitle={`${made.file_count} file${made.file_count === 1 ? "" : "s"} · ${size(made.size_bytes)}`}
        />

        <section className="card">
          <div className="card-body">
            {made.notified ? (
              <p>
                <b>{made.to_name}</b> has been e-mailed a link at{" "}
                <span className="mono">{made.to_email}</span>. No account is needed to
                open it.
              </p>
            ) : (
              <div className="alert alert-warning">
                <b>The e-mail did not go.</b> Mail is not set up on this server, which is a
                supported way to run the platform. Send the link below by hand.
              </div>
            )}

            <label className="field">
              <span className="field-label">The link</span>
              <input className="input mono" readOnly value={made.collect_url ?? ""} />
              <span className="field-help">
                Anyone with this can download the bundle until{" "}
                {made.expires_at ? formatDate(made.expires_at) : "it is deleted"}. It reaches
                nothing else in the archive.
              </span>
            </label>

            {made.folder_on_disk && (
              <label className="field">
                <span className="field-label">And on the disk</span>
                {/* Never a link. The platform cannot open a folder on your
                    machine, and rendering this in blue would be a promise it
                    cannot keep. */}
                <div className="input input-static mono small">{made.folder_on_disk}</div>
                <span className="field-help">
                  The same files, in named folders, on the disk this platform was given.
                  On that machine you can simply open it.
                </span>
              </label>
            )}

            {made.missing && made.missing.length > 0 && (
              <div className="alert alert-warning small">
                <b>{made.missing.length} file(s) were expected and not on the disk.</b>
                <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                  {made.missing.map((name) => (
                    <li key={name}>{name}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="row-tight" style={{ marginTop: 12 }}>
              <Link className="btn" to="/sent">
                Everything sent
              </Link>
            </div>
          </div>
        </section>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Send files"
        subtitle="A link anybody can open, without an account"
      />

      {total === 0 ? (
        <Empty title="Nothing chosen yet">
          Choose photographs in <Link to="/media">Media</Link> or spreadsheets in{" "}
          <Link to="/sheets">Sheets</Link>, then use “Send these to somebody”.
        </Empty>
      ) : (
        <section className="card">
          <div className="card-body">
            <p className="muted small" style={{ marginTop: 0 }}>
              {[
                photographs.length && `${photographs.length} photograph(s)`,
                documents.length && `${documents.length} document(s)`,
                sheets.length && `${sheets.length} sheet(s)`,
              ]
                .filter(Boolean)
                .join(", ")}
              . Sheets go out both as they arrived and up to date, where an up-to-date
              copy exists.
            </p>

            <div className="form-grid">
              <label className="field form-cell" style={{ gridColumn: "span 12" }}>
                <span className="field-label">What is this?</span>
                <input
                  className="input"
                  autoFocus
                  value={title}
                  placeholder="Photographs of the painted jar, for the ministry"
                  onChange={(event) => setTitle(event.target.value)}
                />
                <span className="field-help">
                  Used in the e-mail, on the download page, and as the name of the folder
                  on the disk.
                </span>
              </label>

              <label className="field form-cell" style={{ gridColumn: "span 6" }}>
                <span className="field-label">Who is it for?</span>
                <input
                  className="input"
                  value={toName}
                  placeholder="Layla Haddad"
                  onChange={(event) => setToName(event.target.value)}
                />
              </label>

              <label className="field form-cell" style={{ gridColumn: "span 6" }}>
                <span className="field-label">Their e-mail</span>
                <input
                  className="input"
                  type="email"
                  value={toEmail}
                  placeholder="layla@ministry.example"
                  onChange={(event) => setToEmail(event.target.value)}
                />
              </label>

              <label className="field form-cell" style={{ gridColumn: "span 12" }}>
                <span className="field-label">A note for them (optional)</span>
                <textarea
                  className="input"
                  rows={3}
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                />
              </label>

              <label className="field form-cell" style={{ gridColumn: "span 4" }}>
                <span className="field-label">The link lasts</span>
                <select
                  className="input"
                  value={days}
                  onChange={(event) => setDays(event.target.value)}
                >
                  <option value="7">A week</option>
                  <option value="30">A month</option>
                  <option value="90">Three months</option>
                  <option value="365">A year</option>
                </select>
              </label>
            </div>

            {send.error && <ErrorNote message={send.error} />}

            <div className="row-tight" style={{ marginTop: 12 }}>
              <button
                type="button"
                className="btn btn-primary"
                disabled={!title.trim() || !toName.trim() || !toEmail.trim() || send.running}
                onClick={() => void send.run()}
              >
                {send.running ? "Preparing…" : "Prepare it and send the link"}
              </button>
            </div>
          </div>
        </section>
      )}
    </>
  );
}

export function SentOutgoing() {
  const deliveries = useQuery<Page<Delivery>>(
    (signal) => api.get("/deliveries", { limit: 100 }, signal),
    [],
  );

  const remove = useAction(async (id: string) => {
    await api.delete(`/deliveries/${id}`);
    deliveries.reload();
  });

  const rows = deliveries.data?.items ?? [];

  return (
    <>
      <PageHeader
        title="Sent"
        subtitle="What has gone out of the institution, and to whom"
      />

      <DiskFolder />

      {remove.error && <ErrorNote message={remove.error} />}

      {deliveries.loading ? (
        <Loading rows={4} />
      ) : deliveries.error ? (
        <ErrorNote message={deliveries.error} onRetry={deliveries.reload} />
      ) : rows.length === 0 ? (
        <Empty title="Nothing has been sent yet">
          Choose files in Media or Sheets and use “Send these to somebody”.
        </Empty>
      ) : (
        rows.map((item) => (
          <section key={item.id} className="card" style={{ marginBottom: 12 }}>
            <div className="card-body">
              <div
                className="row-tight"
                style={{ justifyContent: "space-between", flexWrap: "wrap" }}
              >
                <div style={{ minWidth: 0 }}>
                  <div className="strong">{item.title}</div>
                  <div className="muted small">
                    {item.to_name} · <span className="mono">{item.to_email}</span> ·{" "}
                    {item.file_count} file{item.file_count === 1 ? "" : "s"} ·{" "}
                    {size(item.size_bytes)} · {formatDate(item.created_at)}
                    {item.owner_label && ` · sent by ${item.owner_label}`}
                  </div>
                  <div className="muted small">
                    {item.collected_count > 0
                      ? `Collected ${item.collected_count} time${item.collected_count === 1 ? "" : "s"}, last ${formatDateTime(item.collected_at)}`
                      : item.notified
                        ? "E-mailed. Not collected yet."
                        : "Not e-mailed — mail is not set up on this server."}
                    {item.expires_at && ` · link ends ${formatDate(item.expires_at)}`}
                  </div>
                  {item.folder_on_disk && (
                    <div className="mono small muted" style={{ marginTop: 4 }}>
                      {item.folder_on_disk}
                    </div>
                  )}
                </div>
                <Badge value={TONE[item.status] ?? "archived"} kind="status" label={item.status} />
              </div>

              {item.status !== "expired" && (
                <div className="row-tight" style={{ marginTop: 10 }}>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    disabled={remove.running}
                    title="Deletes the bundle from the disk. Every file is still in the archive."
                    onClick={() => void remove.run(item.id)}
                  >
                    Delete the bundle
                  </button>
                  <span className="muted small">
                    The archive's own copy of every file stays where it is.
                  </span>
                </div>
              )}
            </div>
          </section>
        ))
      )}
    </>
  );
}

export default SendOutgoing;

/**
 * The archive as folders, on the disk, for picking things up locally.
 *
 * The file store is content-addressed on purpose — `photographs/ab/cd/9f3e….jpg`
 * — which is right for a store and useless for a person standing in front of a
 * folder. The mirror is the other view: the same files, in folders named after
 * the records, so the institution can reach its own material without going
 * through a browser at all.
 *
 * A button rather than a schedule. A second copy of every photograph is a real
 * cost in disk and time, and a platform that quietly doubles its own storage in
 * the background is one that fills a disk at three in the morning.
 */
function DiskFolder() {
  const state = useQuery<{
    folder_on_disk: string;
    exists: boolean;
    files: number;
    size_bytes: number;
    built_at?: string | null;
  }>((signal) => api.get("/mirror", undefined, signal), []);

  const [outcome, setOutcome] = useState<string | null>(null);

  const build = useAction(async () => {
    const done = await api.post<{ detail: string }>("/mirror", {});
    setOutcome(done.detail);
    state.reload();
  });

  const it = state.data;

  return (
    <section className="card" style={{ marginBottom: 16 }}>
      <div className="card-header">
        <span className="card-title">The folder on your disk</span>
        {it?.built_at && (
          <span className="muted small">last built {formatDateTime(it.built_at)}</span>
        )}
      </div>
      <div className="card-body">
        <p className="small muted" style={{ marginTop: 0 }}>
          Everything the platform holds, copied into folders named after the records —
          <span className="mono"> Sites / TED-A North trench / Photographs</span>. Nothing
          is moved: the platform keeps its own copy of every file, so deleting this folder
          costs nothing but disk.
        </p>

        {it && (
          <>
            {/* Deliberately not a link. A web page cannot open a folder on your
                machine, and rendering this in blue would promise that it can. */}
            <div className="input input-static mono small">{it.folder_on_disk}</div>
            <p className="muted small">
              {it.exists
                ? `${it.files.toLocaleString()} file${it.files === 1 ? "" : "s"} · ${size(it.size_bytes)}`
                : "Not built yet."}
            </p>
          </>
        )}

        {build.error && <ErrorNote message={build.error} />}
        {outcome && <div className="alert alert-info small">{outcome}</div>}

        <button
          type="button"
          className="btn btn-sm"
          disabled={build.running}
          onClick={() => void build.run()}
        >
          {build.running
            ? "Writing the folders…"
            : it?.exists
              ? "Build it again"
              : "Build the folder"}
        </button>
      </div>
    </section>
  );
}
