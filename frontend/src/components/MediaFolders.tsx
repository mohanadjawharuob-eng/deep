/**
 * Files that exist, and are not in here.
 *
 * A season produces four hundred gigabytes of raw frames. Uploading all of it is
 * sometimes right and sometimes absurd — it is on the project drive already,
 * backed up already, and nobody is going to look at the RAWs through a web page.
 *
 * What is not optional is that the record says the material exists. A site page
 * that is silent about four hundred gigabytes reads as complete, and the drive
 * gets reformatted by somebody who checked the archive first.
 *
 * The one design rule here: **never make the path look like a link.** It is a
 * note. The platform cannot open it, cannot check it, and cannot tell you when
 * it stops being true. Rendering it in blue and underlined would be a promise
 * that cannot be kept, so it is monospace on a plain ground, and the panel says
 * so in as many words.
 */

import { useState } from "react";

import { api, type Page } from "../lib/api";
import { useAction, useQuery, useSession } from "../lib/hooks";
import { ErrorNote, Loading, formatDate, humanise } from "./ui";

export type MediaFolder = {
  id: string;
  label: string;
  kind: string;
  path: string;
  medium?: string | null;
  item_count?: number | null;
  size_gb?: number | null;
  recorded_on?: string | null;
  is_backed_up?: boolean | null;
  note?: string | null;
};

/** What the API accepts, in the order a person would fill it in. */
const KINDS = [
  "photographs",
  "drawings",
  "scans",
  "models_3d",
  "survey",
  "documents",
  "raw",
  "other",
];

type Parent = { project_id?: string; site_id?: string; artifact_id?: string; context_id?: string };

export function MediaFolders({ parent, title = "Files kept elsewhere" }: { parent: Parent; title?: string }) {
  const { can } = useSession();
  const mayEdit = can("archaeology", "contributor");
  const [adding, setAdding] = useState(false);

  const query = Object.entries(parent).find(([, value]) => value);
  const folders = useQuery<Page<MediaFolder>>(
    (signal) => api.get("/media-folders", { ...parent, limit: 100 }, signal),
    [query?.[1]],
  );

  const rows = folders.data?.items ?? [];

  return (
    <section className="card" style={{ marginTop: 16 }}>
      <div className="card-header">
        <span className="card-title">{title}</span>
        {mayEdit && !adding && (
          <button type="button" className="btn btn-sm" onClick={() => setAdding(true)}>
            Record a folder…
          </button>
        )}
      </div>

      <div className="card-body">
        <p className="muted small" style={{ marginTop: 0 }}>
          For material that exists and is not being uploaded — a season's raw
          frames, a photogrammetry set, a shelf of discs. These are{" "}
          <b>notes, not links</b>: the platform cannot open a path, check it, or
          tell you when it stops being true.
        </p>

        {adding && (
          <AddFolder
            parent={parent}
            onClose={() => setAdding(false)}
            onAdded={() => {
              setAdding(false);
              folders.reload();
            }}
          />
        )}

        {folders.loading ? (
          <Loading rows={2} />
        ) : folders.error ? (
          <ErrorNote message={folders.error} onRetry={folders.reload} />
        ) : rows.length === 0 ? (
          <p className="muted small" style={{ marginBottom: 0 }}>
            Nothing recorded.
          </p>
        ) : (
          <ul className="folder-list">
            {rows.map((folder) => (
              <li key={folder.id} className="folder">
                <div className="folder-head">
                  <span className="strong">{folder.label}</span>
                  <span className="badge">{humanise(folder.kind)}</span>
                  {folder.is_backed_up === true && <span className="badge badge-ok">backed up</span>}
                  {folder.is_backed_up === false && (
                    <span className="badge badge-warning">not backed up</span>
                  )}
                  {mayEdit && (
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm folder-remove"
                      onClick={async () => {
                        await api.delete(`/media-folders/${folder.id}`);
                        folders.reload();
                      }}
                      title="Forget this note. Nothing on disk is touched."
                    >
                      Remove
                    </button>
                  )}
                </div>

                {/* Selectable, so it can be copied and pasted into Explorer —
                    which is the only thing anybody will ever do with it. */}
                <code className="folder-path">{folder.path}</code>

                <div className="folder-facts muted small">
                  {[
                    folder.medium,
                    folder.item_count != null && `${folder.item_count.toLocaleString()} files`,
                    folder.size_gb != null && `${folder.size_gb} GB`,
                    folder.recorded_on && `checked ${formatDate(folder.recorded_on)}`,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </div>
                {folder.note && <div className="muted small">{folder.note}</div>}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function AddFolder({
  parent,
  onClose,
  onAdded,
}: {
  parent: Parent;
  onClose: () => void;
  onAdded: () => void;
}) {
  const [label, setLabel] = useState("");
  const [path, setPath] = useState("");
  const [kind, setKind] = useState("photographs");
  const [medium, setMedium] = useState("");
  const [count, setCount] = useState("");
  const [size, setSize] = useState("");
  const [backedUp, setBackedUp] = useState("");
  const [note, setNote] = useState("");

  const save = useAction(async () => {
    await api.post("/media-folders", {
      ...parent,
      label,
      path,
      kind,
      medium: medium || undefined,
      item_count: count ? Number(count) : undefined,
      size_gb: size ? Number(size) : undefined,
      // "" means nobody has said, which is a third state and not "no".
      is_backed_up: backedUp === "" ? undefined : backedUp === "yes",
      note: note || undefined,
    });
    onAdded();
  });

  return (
    <div className="inset-form">
      <div className="form-grid">
        <div className="form-cell" style={{ gridColumn: "span 8" }}>
          <div className="form-label">
            What is it <span className="required">*</span>
          </div>
          <input
            className="input"
            value={label}
            maxLength={300}
            placeholder="Trench A season photographs"
            onChange={(event) => setLabel(event.target.value)}
          />
        </div>
        <div className="form-cell" style={{ gridColumn: "span 4" }}>
          <div className="form-label">Kind</div>
          <select className="input" value={kind} onChange={(event) => setKind(event.target.value)}>
            {KINDS.map((value) => (
              <option key={value} value={value}>
                {humanise(value)}
              </option>
            ))}
          </select>
        </div>

        <div className="form-cell" style={{ gridColumn: "span 12" }}>
          <div className="form-label">
            Folder <span className="required">*</span>
          </div>
          <input
            className="input mono"
            value={path}
            maxLength={1000}
            placeholder="D:\Seasons\2019\TrenchA"
            onChange={(event) => setPath(event.target.value)}
          />
          <div className="form-help">
            Exactly as you would type it. A Windows path, a network share, or a
            shelf reference for a box of discs — all fine, none of them checked.
          </div>
        </div>

        <div className="form-cell" style={{ gridColumn: "span 6" }}>
          <div className="form-label">Which disk</div>
          <input
            className="input"
            value={medium}
            maxLength={300}
            placeholder="External drive labelled DIG-2019"
            onChange={(event) => setMedium(event.target.value)}
          />
          <div className="form-help">
            Worth the ten seconds. A path with no disk names a folder on a
            machine nobody can identify in five years.
          </div>
        </div>
        <div className="form-cell" style={{ gridColumn: "span 3" }}>
          <div className="form-label">How many files</div>
          <input
            className="input"
            type="number"
            min={0}
            value={count}
            onChange={(event) => setCount(event.target.value)}
          />
        </div>
        <div className="form-cell" style={{ gridColumn: "span 3" }}>
          <div className="form-label">Size (GB)</div>
          <input
            className="input"
            type="number"
            min={0}
            step="0.1"
            value={size}
            onChange={(event) => setSize(event.target.value)}
          />
        </div>

        <div className="form-cell" style={{ gridColumn: "span 4" }}>
          <div className="form-label">Backed up elsewhere?</div>
          <select
            className="input"
            value={backedUp}
            onChange={(event) => setBackedUp(event.target.value)}
          >
            <option value="">Nobody has said</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        </div>
        <div className="form-cell" style={{ gridColumn: "span 8" }}>
          <div className="form-label">Note</div>
          <input
            className="input"
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
        </div>
      </div>

      {save.error && <ErrorNote message={save.error} />}

      <div className="row-tight" style={{ marginTop: 10 }}>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          disabled={!label.trim() || !path.trim() || save.running}
          onClick={() => void save.run()}
        >
          {save.running ? "Saving…" : "Record it"}
        </button>
        <button type="button" className="btn btn-sm" onClick={onClose}>
          Cancel
        </button>
      </div>
    </div>
  );
}
