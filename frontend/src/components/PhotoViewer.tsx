/**
 * One photograph, large, with the things you can do to it.
 *
 * A wall of thumbnails you cannot act on is half a feature: you can see that a
 * picture is wrong, or is a duplicate, or is waiting for somebody to look at
 * it, and then there is nothing to click. Every one of those actions already
 * existed in the API and in no screen.
 *
 * So: click a picture, get it big, and get the four things anybody wants —
 * look at it properly, approve it, download it, delete it. The destructive one
 * asks first and says what goes with it; the rest do not, because a download
 * that asks permission is a download that gets abandoned.
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import { useAction, useQuery, useSession } from "../lib/hooks";
import { AuthImage, ErrorNote, formatDateTime } from "./ui";

export type ViewablePhoto = {
  id: string;
  title: string;
  description?: string | null;
  photographer?: string | null;
  taken_at?: string | null;
  created_at: string;
  review_status?: string;
  original_filename?: string | null;
  file_size?: number | null;
  width?: number | null;
  height?: number | null;
  project_id?: string | null;
  site_id?: string | null;
  artifact_id?: string | null;
  museum_object_id?: string | null;
};

function recordOf(photo: ViewablePhoto): { to: string; label: string } | null {
  if (photo.museum_object_id) {
    return { to: `/museum/objects/${photo.museum_object_id}`, label: "the museum object" };
  }
  if (photo.artifact_id) return { to: `/artifacts/${photo.artifact_id}`, label: "the find" };
  if (photo.site_id) return { to: `/sites/${photo.site_id}`, label: "the site" };
  if (photo.project_id) return { to: `/projects/${photo.project_id}`, label: "the project" };
  return null;
}

export function PhotoViewer({
  photo,
  onClose,
  onChanged,
}: {
  photo: ViewablePhoto;
  onClose: () => void;
  /** Called after anything that changes the list behind this. */
  onChanged: () => void;
}) {
  const { can, user } = useSession();
  const [confirming, setConfirming] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [note, setNote] = useState("");

  // The full record, for the fields the list does not carry.
  const detail = useQuery<ViewablePhoto>(
    (signal) => api.get(`/photographs/${photo.id}`, undefined, signal),
    [photo.id],
  );
  const it = detail.data ?? photo;

  const mayEdit = can("archaeology", "contributor") || can("museum", "contributor");
  const mayReview = can("archaeology", "supervisor") || can("museum", "supervisor");
  const pending = it.review_status === "pending";

  const approve = useAction(async () => {
    await api.post(`/review/photographs/${it.id}/approve`, {});
    onChanged();
    onClose();
  });

  const reject = useAction(async () => {
    await api.post(`/review/photographs/${it.id}/reject`, { note: note.trim() });
    onChanged();
    onClose();
  });

  const remove = useAction(async () => {
    await api.delete(`/photographs/${it.id}`);
    onChanged();
    onClose();
  });

  const origin = recordOf(it);

  return (
    <div className="modal-scrim" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="viewer" onClick={(event) => event.stopPropagation()}>
        <div className="viewer-image">
          <AuthImage
            path={`/photographs/${it.id}/thumbnail`}
            query={{ size: 1600 }}
            alt={it.title}
            fallback={<span className="muted">This picture could not be loaded.</span>}
          />
        </div>

        <aside className="viewer-side">
          <div className="viewer-head">
            <h2 className="modal-title">{it.title}</h2>
            <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
              Close
            </button>
          </div>

          {pending && (
            <div className="alert alert-warning small">
              <b>Waiting to be looked at.</b> Nobody inside the institution has checked this
              yet — it came from outside, or from somebody whose work is reviewed.
            </div>
          )}

          <dl className="viewer-facts">
            {origin && (
              <>
                <dt>Of</dt>
                <dd>
                  <Link to={origin.to} onClick={onClose}>
                    {origin.label}
                  </Link>
                </dd>
              </>
            )}
            {it.photographer && (
              <>
                <dt>By</dt>
                <dd>{it.photographer}</dd>
              </>
            )}
            <dt>Added</dt>
            <dd>{formatDateTime(it.created_at)}</dd>
            {it.width && it.height && (
              <>
                <dt>Size</dt>
                <dd>
                  {it.width} × {it.height}
                  {it.file_size ? ` · ${Math.round(it.file_size / 1024)} KB` : ""}
                </dd>
              </>
            )}
            {it.original_filename && (
              <>
                <dt>File</dt>
                <dd className="mono small truncate">{it.original_filename}</dd>
              </>
            )}
          </dl>

          {it.description && <p className="small">{it.description}</p>}

          {approve.error && <ErrorNote message={approve.error} />}
          {reject.error && <ErrorNote message={reject.error} />}
          {remove.error && <ErrorNote message={remove.error} />}

          <div className="viewer-actions">
            {pending && mayReview && !rejecting && (
              <>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  disabled={approve.running}
                  onClick={() => void approve.run()}
                >
                  {approve.running ? "Approving…" : "Approve"}
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => setRejecting(true)}
                >
                  Send back…
                </button>
              </>
            )}

            {rejecting && (
              <div className="stack-tight" style={{ width: "100%" }}>
                <label className="field">
                  <span className="field-label">What needs changing?</span>
                  <textarea
                    className="textarea"
                    rows={3}
                    autoFocus
                    value={note}
                    placeholder="Out of focus — please send the other frame."
                    onChange={(event) => setNote(event.target.value)}
                  />
                  {/* Required by the API, and rightly: "rejected" with no
                      reason is a dead end for whoever sent it. */}
                  <span className="field-help">
                    A note is required — otherwise whoever sent it has nothing to act on.
                  </span>
                </label>
                <div className="row-tight">
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    disabled={!note.trim() || reject.running}
                    onClick={() => void reject.run()}
                  >
                    {reject.running ? "Sending back…" : "Send it back"}
                  </button>
                  <button type="button" className="btn btn-sm" onClick={() => setRejecting(false)}>
                    Cancel
                  </button>
                </div>
              </div>
            )}

            <button
              type="button"
              className="btn btn-sm"
              onClick={() => void api.download(`/photographs/${it.id}/download`)}
            >
              Download
            </button>

            {mayEdit && !confirming && (
              <button
                type="button"
                className="btn btn-danger btn-sm"
                onClick={() => setConfirming(true)}
              >
                Delete
              </button>
            )}
          </div>

          {confirming && (
            <div className="alert alert-danger">
              <b>Delete this photograph?</b> The file and its thumbnails go with it. This
              cannot be undone.
              <div className="row-tight" style={{ marginTop: 8 }}>
                <button
                  type="button"
                  className="btn btn-danger-solid btn-sm"
                  disabled={remove.running}
                  onClick={() => void remove.run()}
                >
                  {remove.running ? "Deleting…" : "Yes, delete it"}
                </button>
                <button type="button" className="btn btn-sm" onClick={() => setConfirming(false)}>
                  Keep it
                </button>
              </div>
            </div>
          )}

          {!mayEdit && (
            <p className="muted small" style={{ marginBottom: 0 }}>
              You can look at this but not change it. {user?.username} has no contributor
              access to the module it belongs to.
            </p>
          )}
        </aside>
      </div>
    </div>
  );
}
