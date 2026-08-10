/**
 * Asking somebody outside the platform for a file.
 *
 * The photographs of a find are on a colleague's laptop; the permit scan is in
 * the ministry's mailbox; the survey data is with the contractor. None of them
 * have an account here and none of them are going to make one, so today this is
 * an e-mail thread, a transfer link that expires in a week, and a file that
 * lands in somebody's Downloads folder rather than in the archive.
 *
 * This panel sends a link that puts the file where it belongs. Two things the
 * interface has to be honest about, because both are easy to get wrong:
 *
 * **The link is shown once.** Only its hash is stored, the way a password is,
 * so the platform genuinely cannot show it again — it can only issue a new one.
 * The panel says so beside the link rather than after somebody has closed it.
 *
 * **"Sent" and "not sent" are different states, and both are shown.** A request
 * whose e-mail could not leave the building still has a working link somebody
 * can pass on by hand. What must never happen is the requester waiting on a
 * message that was never delivered.
 */

import { useState } from "react";

import { api, type Page } from "../lib/api";
import { useAction, useQuery, useSession } from "../lib/hooks";
import { ErrorNote, Loading, formatDate, humanise } from "./ui";

export type DataRequest = {
  id: string;
  record_label: string;
  kind: string;
  message?: string | null;
  recipient_email: string;
  recipient_name?: string | null;
  status: "open" | "sent" | "answered" | "closed" | "cancelled";
  delivery_note?: string | null;
  expires_at: string;
  max_uploads: number;
  upload_count: number;
  uploads_left: number;
  sent_at?: string | null;
  created_at: string;
  project_id?: string | null;
  site_id?: string | null;
  artifact_id?: string | null;
  context_id?: string | null;
};

type Created = DataRequest & { invite_url: string };

type Parent = { project_id?: string; site_id?: string; artifact_id?: string; context_id?: string };

const KINDS = [
  { value: "photographs", label: "Photographs" },
  { value: "documents", label: "Documents" },
  { value: "drawings", label: "Drawings" },
  { value: "models_3d", label: "3D models" },
  { value: "anything", label: "Anything" },
];

/** Colour is never the only signal, so each state carries its own word. */
const STATE: Record<DataRequest["status"], { label: string; className: string }> = {
  open: { label: "not sent", className: "badge-warning" },
  sent: { label: "waiting", className: "badge-info" },
  answered: { label: "files arrived", className: "badge-success" },
  closed: { label: "finished", className: "badge" },
  cancelled: { label: "withdrawn", className: "badge" },
};

export function DataRequests({ parent, recordId }: { parent: Parent; recordId: string }) {
  const { can } = useSession();
  const mayAsk = can("archaeology", "contributor") || can("museum", "contributor");
  const [asking, setAsking] = useState(false);
  const [fresh, setFresh] = useState<Created | null>(null);

  const requests = useQuery<Page<DataRequest>>(
    (signal) => api.get("/data-requests", { record_id: recordId, limit: 50 }, signal),
    [recordId],
  );

  const rows = requests.data?.items ?? [];

  return (
    <section className="card" style={{ marginTop: 16 }}>
      <div className="card-header">
        <span className="card-title">Files asked for</span>
        {mayAsk && !asking && (
          <button type="button" className="btn btn-sm" onClick={() => setAsking(true)}>
            Ask somebody for files…
          </button>
        )}
      </div>

      <div className="card-body">
        <p className="muted small" style={{ marginTop: 0 }}>
          Sends a link that lets somebody send files straight into this record.{" "}
          <b>They need no account</b>, and the link does nothing else — it gives no access to
          this record or any other.
        </p>

        {asking && (
          <AskForFiles
            parent={parent}
            onClose={() => setAsking(false)}
            onAsked={(created) => {
              setAsking(false);
              setFresh(created);
              requests.reload();
            }}
          />
        )}

        {fresh && <TheLink created={fresh} onDismiss={() => setFresh(null)} />}

        {requests.loading ? (
          <Loading rows={2} />
        ) : requests.error ? (
          <ErrorNote message={requests.error} onRetry={requests.reload} />
        ) : rows.length === 0 ? (
          <p className="muted small" style={{ marginBottom: 0 }}>
            Nothing asked for.
          </p>
        ) : (
          <ul className="request-list">
            {rows.map((request) => (
              <RequestRow
                key={request.id}
                request={request}
                onChanged={requests.reload}
                onResent={setFresh}
              />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function RequestRow({
  request,
  onChanged,
  onResent,
}: {
  request: DataRequest;
  onChanged: () => void;
  onResent: (created: Created) => void;
}) {
  const state = STATE[request.status];
  const finished = request.status === "closed" || request.status === "cancelled";

  const resend = useAction(async () => {
    onResent(await api.post<Created>(`/data-requests/${request.id}/resend`, {}));
    onChanged();
  });
  const withdraw = useAction(async () => {
    await api.delete(`/data-requests/${request.id}`);
    onChanged();
  });

  return (
    <li className="request">
      <div className="request-head">
        <span className="strong">{humanise(request.kind)}</span>
        <span className={`badge ${state.className}`}>{state.label}</span>
        <span className="muted small">
          {request.recipient_name ? `${request.recipient_name} · ` : ""}
          {request.recipient_email}
        </span>
        {!finished && (
          <span className="row-tight request-actions">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={resend.running}
              onClick={() => void resend.run()}
              title="Issues a new link. The old one stops working."
            >
              {resend.running ? "Sending…" : "Send a new link"}
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={withdraw.running}
              onClick={() => void withdraw.run()}
              title="The link stops working immediately. The request is kept."
            >
              Withdraw
            </button>
          </span>
        )}
      </div>

      {request.message && <div className="small">{request.message}</div>}

      <div className="muted small">
        {[
          `${request.upload_count} of ${request.max_uploads} sent`,
          finished ? null : `link works until ${formatDate(request.expires_at)}`,
          `asked ${formatDate(request.created_at)}`,
        ]
          .filter(Boolean)
          .join(" · ")}
      </div>

      {/* The one thing worse than mail failing is not being told it failed. */}
      {request.status === "open" && request.delivery_note && (
        <div className="alert alert-warning small" style={{ marginTop: 6 }}>
          <b>The e-mail did not go out.</b> {request.delivery_note} The link still works — send a
          new one to copy it and pass it on yourself.
        </div>
      )}

      {resend.error && <ErrorNote message={resend.error} />}
      {withdraw.error && <ErrorNote message={withdraw.error} />}
    </li>
  );
}

/**
 * The link, shown once.
 *
 * Deliberately hard to miss and deliberately not dismissible by accident: this
 * is the only moment it exists outside the recipient's mailbox.
 */
function TheLink({ created, onDismiss }: { created: Created; onDismiss: () => void }) {
  const [copied, setCopied] = useState(false);

  return (
    <div className="alert alert-info" style={{ marginBottom: 12 }}>
      <b>
        {created.status === "sent"
          ? `Sent to ${created.recipient_email}.`
          : "Created, but the e-mail did not go out."}
      </b>{" "}
      This link is shown now and cannot be shown again — only its fingerprint is kept. Copy it if
      you mean to pass it on yourself.
      <code className="folder-path" style={{ marginTop: 8 }}>
        {created.invite_url}
      </code>
      <div className="row-tight" style={{ marginTop: 8 }}>
        <button
          type="button"
          className="btn btn-sm"
          onClick={async () => {
            await navigator.clipboard.writeText(created.invite_url);
            setCopied(true);
          }}
        >
          {copied ? "Copied" : "Copy the link"}
        </button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onDismiss}>
          Done
        </button>
      </div>
    </div>
  );
}

function AskForFiles({
  parent,
  onClose,
  onAsked,
}: {
  parent: Parent;
  onClose: () => void;
  onAsked: (created: Created) => void;
}) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [kind, setKind] = useState("photographs");
  const [message, setMessage] = useState("");
  const [maxUploads, setMaxUploads] = useState("20");
  const [days, setDays] = useState("21");

  const send = useAction(async () => {
    onAsked(
      await api.post<Created>("/data-requests", {
        ...parent,
        recipient_email: email.trim(),
        recipient_name: name.trim() || null,
        kind,
        message: message.trim() || null,
        max_uploads: Number(maxUploads) || 20,
        expires_in_days: Number(days) || 21,
      }),
    );
  });

  return (
    <div className="inset-form">
      <div className="form-grid">
        <label className="field" style={{ gridColumn: "span 5" }}>
          <span className="field-label">
            Their e-mail<span className="required"> *</span>
          </span>
          <input
            className="input"
            type="email"
            value={email}
            placeholder="photographer@example.org"
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>

        <label className="field" style={{ gridColumn: "span 4" }}>
          <span className="field-label">Their name</span>
          <input
            className="input"
            value={name}
            placeholder="So the e-mail can greet them"
            onChange={(event) => setName(event.target.value)}
          />
        </label>

        <label className="field" style={{ gridColumn: "span 3" }}>
          <span className="field-label">What you need</span>
          <select className="input" value={kind} onChange={(event) => setKind(event.target.value)}>
            {KINDS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>

        <label className="field" style={{ gridColumn: "span 12" }}>
          <span className="field-label">Your message</span>
          <textarea
            className="textarea"
            rows={3}
            value={message}
            placeholder="The trench shots from the last week of the season, please."
            onChange={(event) => setMessage(event.target.value)}
          />
          <span className="field-help">Goes into the e-mail as written.</span>
        </label>

        <label className="field" style={{ gridColumn: "span 3" }}>
          <span className="field-label">How many files</span>
          <input
            className="input"
            type="number"
            min={1}
            max={200}
            value={maxUploads}
            onChange={(event) => setMaxUploads(event.target.value)}
          />
          <span className="field-help">The link closes itself once it is full.</span>
        </label>

        <label className="field" style={{ gridColumn: "span 3" }}>
          <span className="field-label">Link lasts (days)</span>
          <input
            className="input"
            type="number"
            min={1}
            max={180}
            value={days}
            onChange={(event) => setDays(event.target.value)}
          />
        </label>
      </div>

      {send.error && <ErrorNote message={send.error} />}

      <div className="row-tight" style={{ marginTop: 10 }}>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          disabled={!email.trim() || send.running}
          onClick={() => void send.run()}
        >
          {send.running ? "Sending…" : "Send the request"}
        </button>
        <button type="button" className="btn btn-sm" onClick={onClose}>
          Cancel
        </button>
      </div>
    </div>
  );
}
