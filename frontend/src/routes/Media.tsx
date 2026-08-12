/**
 * The media library: a tree of folders, and what is in the one you open.
 *
 * Two axes on the same photographs, and keeping them apart is the whole
 * design. A picture **belongs to a record** — a site, a find, an object — and
 * that link decides permissions, drives search, and survives anybody
 * reorganising their filing. A picture is also **in a folder**, which is a
 * drawer somebody made because "2024 / Trench A / working shots" is how they
 * think, not a fact about the archive.
 *
 * So the tree never claims to be the archive. Deleting a folder deletes
 * nothing; the files become unfiled and are still on their records, and the
 * interface says so on the button rather than in a manual.
 *
 * **Unfiled** is a real place in the list, at the top, because a filing system
 * whose unfiled pile is invisible is one where things quietly stop being
 * filed.
 */

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api, type Page } from "../lib/api";
import { useAction, useQuery, useSession } from "../lib/hooks";
import {
  AuthImage,
  ErrorNote,
  Loading,
  PageHeader,
  formatDate,
} from "../components/ui";
import { PhotoViewer } from "../components/PhotoViewer";

export type Folder = {
  id: string;
  name: string;
  parent_id: string | null;
  kind: "general" | "facebook" | "instagram";
  note?: string | null;
  file_count: number;
};

type Photo = {
  id: string;
  title: string;
  created_at: string;
  taken_at?: string | null;
  review_status?: string;
  folder_id?: string | null;
  project_id?: string | null;
  site_id?: string | null;
  artifact_id?: string | null;
  museum_object_id?: string | null;
};

/** Where a photograph belongs in the *archive*, as opposed to in the filing. */
function recordOf(photo: Photo): { to: string; label: string } | null {
  if (photo.museum_object_id) {
    return { to: `/museum/objects/${photo.museum_object_id}`, label: "museum object" };
  }
  if (photo.artifact_id) return { to: `/artifacts/${photo.artifact_id}`, label: "find" };
  if (photo.site_id) return { to: `/sites/${photo.site_id}`, label: "site" };
  if (photo.project_id) return { to: `/projects/${photo.project_id}`, label: "project" };
  return null;
}

/** Children of one folder, sorted the way a person reads a list. */
function childrenOf(folders: Folder[], parent: string | null) {
  return folders
    .filter((folder) => folder.parent_id === parent)
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
}

export function Media({
  /** Only this branch of the tree. The social media screen passes a channel. */
  onlyKind,
  title = "Media",
  subtitle = "Photographs and documents, in folders you make.",
}: {
  onlyKind?: Folder["kind"];
  title?: string;
  subtitle?: string;
} = {}) {
  const { can } = useSession();
  const mayEdit = can("archaeology", "contributor") || can("museum", "contributor");

  const [openId, setOpenId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [adding, setAdding] = useState<string | null | false>(false);
  const [viewing, setViewing] = useState<Photo | null>(null);

  const folders = useQuery<Folder[]>(
    (signal) => api.get("/folders", undefined, signal),
    [],
  );

  const all = folders.data ?? [];
  // A channel view shows that channel's own branch: the roots of the given
  // kind, and everything beneath them, whatever kind those are.
  const roots = useMemo(() => {
    if (!onlyKind) return childrenOf(all, null);
    return all.filter((folder) => folder.kind === onlyKind && folder.parent_id === null);
  }, [all, onlyKind]);

  const photos = useQuery<Page<Photo>>(
    (signal) =>
      api.get("/photographs", { folder_id: openId ?? "none", limit: 100 }, signal),
    [openId],
  );

  const open = all.find((folder) => folder.id === openId) ?? null;
  const rows = photos.data?.items ?? [];

  const refresh = () => {
    folders.reload();
    photos.reload();
    setChosen(new Set());
  };

  const move = useAction(async (target: string) => {
    await api.post(`/folders/${target}/contents`, { photograph_ids: [...chosen] });
    refresh();
  });

  const remove = useAction(async (id: string) => {
    await api.delete(`/folders/${id}`);
    if (openId === id) setOpenId(null);
    refresh();
  });

  const toggle = (id: string) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const pick = (id: string) =>
    setChosen((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const Branch = ({ folder, depth }: { folder: Folder; depth: number }) => {
    const kids = childrenOf(all, folder.id);
    const isOpen = expanded.has(folder.id);
    return (
      <>
        <div className={`tree-row ${openId === folder.id ? "active" : ""}`}>
          <button
            type="button"
            className="tree-toggle"
            style={{ marginLeft: depth * 14, visibility: kids.length ? "visible" : "hidden" }}
            onClick={() => toggle(folder.id)}
            aria-label={isOpen ? "Collapse" : "Expand"}
          >
            {isOpen ? "▾" : "▸"}
          </button>
          <button type="button" className="tree-label" onClick={() => setOpenId(folder.id)}>
            <span className="truncate">{folder.name}</span>
            <span className="tree-count">{folder.file_count || ""}</span>
          </button>
        </div>
        {isOpen && kids.map((kid) => <Branch key={kid.id} folder={kid} depth={depth + 1} />)}
      </>
    );
  };

  if (folders.loading) return <Loading rows={5} />;

  return (
    <div>
      <PageHeader title={title} subtitle={subtitle} />

      <div className="media-layout">
        {/* ------------------------------------------------------- the tree */}
        <aside className="tree-panel">
          <div className={`tree-row ${openId === null ? "active" : ""}`}>
            <span className="tree-toggle" style={{ visibility: "hidden" }} />
            <button type="button" className="tree-label" onClick={() => setOpenId(null)}>
              <span className="truncate">Unfiled</span>
            </button>
          </div>

          {roots.map((folder) => (
            <Branch key={folder.id} folder={folder} depth={0} />
          ))}

          {folders.error && <ErrorNote message={folders.error} onRetry={folders.reload} />}

          {mayEdit && (
            <div className="row-tight" style={{ marginTop: 10, flexWrap: "wrap" }}>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => setAdding(open ? open.id : null)}
              >
                {open ? `New folder in ${open.name}` : "New folder"}
              </button>
            </div>
          )}

          {adding !== false && (
            <NewFolder
              parentId={adding}
              kind={onlyKind}
              onClose={() => setAdding(false)}
              onMade={() => {
                // Open the parent, or the folder somebody just made is
                // invisible and they make it again.
                if (adding) setExpanded((current) => new Set(current).add(adding));
                setAdding(false);
                folders.reload();
              }}
            />
          )}
        </aside>

        {/* ------------------------------------------------------ the files */}
        <section className="media-body">
          <div className="toolbar">
            <span className="strong">{open ? open.name : "Unfiled"}</span>
            <span className="muted small">
              {photos.data?.total ?? 0} file{photos.data?.total === 1 ? "" : "s"}
            </span>

            {mayEdit && open && (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => void remove.run(open.id)}
                title="The files in it are not deleted — they become unfiled"
              >
                Remove this folder
              </button>
            )}
          </div>

          {remove.error && <ErrorNote message={remove.error} />}
          {move.error && <ErrorNote message={move.error} />}

          {chosen.size > 0 && (
            <div className="alert alert-info">
              <b>
                {chosen.size} chosen.
              </b>{" "}
              Move to:{" "}
              <select
                className="input input-sm"
                style={{ width: "auto", display: "inline-block" }}
                value=""
                onChange={(event) => event.target.value && void move.run(event.target.value)}
              >
                <option value="">choose a folder…</option>
                <option value="none">Unfiled</option>
                {all.map((folder) => (
                  <option key={folder.id} value={folder.id}>
                    {folder.name}
                  </option>
                ))}
              </select>
              <Link
                className="btn btn-sm"
                to={`/outgoing?photographs=${[...chosen].join(",")}`}
              >
                Send these to somebody
              </Link>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setChosen(new Set())}
              >
                Clear
              </button>
            </div>
          )}

          {photos.loading ? (
            <Loading rows={3} />
          ) : photos.error ? (
            <ErrorNote message={photos.error} onRetry={photos.reload} />
          ) : rows.length === 0 ? (
            <p className="muted">
              {open
                ? "Nothing filed here yet. Open Unfiled, choose some photographs and move them in."
                : "Nothing unfiled — everything has been put away."}
            </p>
          ) : (
            <div className="gallery">
              {rows.map((photo) => {
                const origin = recordOf(photo);
                return (
                  <figure
                    key={photo.id}
                    className={`gallery-tile pickable ${chosen.has(photo.id) ? "chosen" : ""}`}
                  >
                    {/* Clicking a photograph opens it. Choosing several to
                        move is the tick in the corner, deliberately separate:
                        a grid where the only thing a click does is select is a
                        grid where nobody can look at their own pictures. */}
                    <button
                      type="button"
                      className="pick-target"
                      onClick={() => setViewing(photo)}
                      aria-label={`Open ${photo.title}`}
                    >
                      <AuthImage
                        path={`/photographs/${photo.id}/thumbnail`}
                        query={{ size: 600 }}
                        alt={photo.title}
                        fallback={<span className="small muted">could not load</span>}
                      />
                    </button>
                    <label className="tile-tick" title="Choose it, to move or file it">
                      <input
                        type="checkbox"
                        checked={chosen.has(photo.id)}
                        onChange={() => pick(photo.id)}
                        aria-label={`Choose ${photo.title}`}
                      />
                    </label>
                    <figcaption>
                      <span className="strong truncate" title={photo.title}>
                        {photo.title}
                      </span>
                      <span className="muted small">
                        {/* The record, always. The folder is where somebody
                            put it; the record is what it is *of*. */}
                        {origin ? (
                          <Link to={origin.to}>on a {origin.label}</Link>
                        ) : (
                          "not attached to a record"
                        )}
                        {" · "}
                        {formatDate(photo.taken_at ?? photo.created_at)}
                      </span>
                    </figcaption>
                  </figure>
                );
              })}
            </div>
          )}
        </section>
      </div>

      {viewing && (
        <PhotoViewer
          photo={viewing}
          onClose={() => setViewing(null)}
          onChanged={() => {
            photos.reload();
            folders.reload();
          }}
        />
      )}
    </div>
  );
}

function NewFolder({
  parentId,
  kind,
  onClose,
  onMade,
}: {
  parentId: string | null;
  kind?: Folder["kind"];
  onClose: () => void;
  onMade: () => void;
}) {
  const [name, setName] = useState("");

  const save = useAction(async () => {
    await api.post("/folders", {
      name: name.trim(),
      parent_id: parentId,
      // A folder made inside a channel is an ordinary folder; only a root of
      // the channel view carries the channel's kind.
      kind: parentId === null ? (kind ?? "general") : "general",
    });
    onMade();
  });

  return (
    <div className="inset-form" style={{ marginTop: 8 }}>
      <label className="field">
        <span className="field-label">Name</span>
        <input
          className="input"
          autoFocus
          value={name}
          placeholder={parentId ? "Working shots" : "2024"}
          onChange={(event) => setName(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && name.trim()) void save.run();
            if (event.key === "Escape") onClose();
          }}
        />
      </label>
      {save.error && <ErrorNote message={save.error} />}
      <div className="row-tight" style={{ marginTop: 8 }}>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          disabled={!name.trim() || save.running}
          onClick={() => void save.run()}
        >
          {save.running ? "Making…" : "Make it"}
        </button>
        <button type="button" className="btn btn-sm" onClick={onClose}>
          Cancel
        </button>
      </div>
    </div>
  );
}

export default Media;
