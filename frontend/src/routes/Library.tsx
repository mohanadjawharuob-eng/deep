/**
 * The library.
 *
 * Three columns, the way every reference manager is laid out, because that is
 * the shape people already know: folders on the left, references in the middle,
 * the one you are reading on the right.
 *
 * The right-hand panel is where this stops being a reference manager. Under the
 * fields is **What it is about** — the records this reference has been attached
 * to, and where in it. "Smith 1987 is about this site" is a bibliography entry;
 * "Smith 1987, 88-91, describes context 1042" is a finding aid, and it is the
 * sentence nobody writes down because there has never been anywhere to write it.
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import { api, type Page } from "../lib/api";
import { useAction, useDebounced, useQuery, useSession } from "../lib/hooks";
import {
  Empty,
  ErrorNote,
  Loading,
  PageHeader,
  SearchInput,
  humanise,
} from "../components/ui";

type Reference = {
  id: string;
  reference_type: string;
  title: string;
  authors?: string | null;
  editors?: string | null;
  year?: number | null;
  journal?: string | null;
  volume?: string | null;
  issue?: string | null;
  pages?: string | null;
  publisher?: string | null;
  place?: string | null;
  doi?: string | null;
  url?: string | null;
  abstract?: string | null;
  notes?: string | null;
  keywords?: string[] | null;
  citation_key?: string | null;
  label: string;
  collection_ids: string[];
  link_count: number;
};

type Folder = {
  id: string;
  name: string;
  parent_id?: string | null;
  reference_count: number;
};

type RefLink = {
  id: string;
  locator?: string | null;
  note?: string | null;
  target_kind?: string | null;
  target_label?: string | null;
  site_id?: string | null;
  artifact_id?: string | null;
  museum_object_id?: string | null;
  context_id?: string | null;
  project_id?: string | null;
};

const TYPES = [
  "article",
  "book",
  "chapter",
  "thesis",
  "report",
  "conference",
  "archive",
  "dataset",
  "map",
  "webpage",
  "other",
];

const PAGE = 50;

export function Library() {
  const { can } = useSession();
  const mayEdit = can("archaeology", "contributor");

  const [term, setTerm] = useState("");
  const search = useDebounced(term);
  const [folderId, setFolderId] = useState("");
  const [type, setType] = useState("");
  const [offset, setOffset] = useState(0);
  const [openId, setOpenId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState(false);

  const folders = useQuery<Folder[]>(
    (signal) => api.get("/library/collections", undefined, signal),
    [],
  );

  const references = useQuery<Page<Reference>>(
    (signal) =>
      api.get(
        "/library/references",
        {
          q: search || undefined,
          collection_id: folderId || undefined,
          reference_type: type || undefined,
          limit: PAGE,
          offset,
        },
        signal,
      ),
    [search, folderId, type, offset],
  );

  const rows = references.data?.items ?? [];
  const open = rows.find((row) => row.id === openId) ?? null;

  const download = useAction(() =>
    api.download("/library/export.bib", {
      collection_id: folderId || undefined,
      q: search || undefined,
    }),
  );

  const refresh = () => {
    references.reload();
    folders.reload();
  };

  return (
    <>
      <PageHeader
        title="Library"
        subtitle={
          references.data
            ? `${references.data.total.toLocaleString()} reference${
                references.data.total === 1 ? "" : "s"
              }`
            : "References, and what each one is about"
        }
        actions={
          <>
            <button
              type="button"
              className="btn"
              onClick={() => void download.run()}
              disabled={download.running}
            >
              {download.running ? "Preparing…" : "Export .bib"}
            </button>
            {mayEdit && (
              <>
                <button type="button" className="btn" onClick={() => setImporting(true)}>
                  Import .bib
                </button>
                <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}>
                  Add a reference
                </button>
              </>
            )}
          </>
        }
      />

      {importing && (
        <ImportBib
          folders={folders.data ?? []}
          onClose={() => setImporting(false)}
          onDone={() => {
            setImporting(false);
            refresh();
          }}
        />
      )}

      {adding && (
        <EditReference
          folders={folders.data ?? []}
          onClose={() => setAdding(false)}
          onSaved={() => {
            setAdding(false);
            refresh();
          }}
        />
      )}

      <div className="toolbar">
        <SearchInput
          value={term}
          onChange={(value) => {
            setTerm(value);
            setOffset(0);
          }}
          placeholder="Title, author, journal, keyword…"
        />
        <select
          className="input input-sm"
          value={type}
          onChange={(event) => {
            setType(event.target.value);
            setOffset(0);
          }}
        >
          <option value="">Any kind</option>
          {TYPES.map((value) => (
            <option key={value} value={value}>
              {humanise(value)}
            </option>
          ))}
        </select>
      </div>

      <div className="library">
        {/* Folders. A reference can be in several at once, so these filter
            rather than contain — which is why removing one keeps its
            references and the message on the button says so. */}
        <aside className="library-folders">
          <button
            type="button"
            className={`folder-item ${folderId === "" ? "chosen" : ""}`}
            onClick={() => {
              setFolderId("");
              setOffset(0);
            }}
          >
            <span>Everything</span>
            <span className="muted small">{references.data?.total ?? ""}</span>
          </button>

          {(folders.data ?? []).map((folder) => (
            <button
              key={folder.id}
              type="button"
              className={`folder-item ${folderId === folder.id ? "chosen" : ""}`}
              style={{ paddingLeft: folder.parent_id ? 26 : undefined }}
              onClick={() => {
                setFolderId(folder.id);
                setOffset(0);
              }}
            >
              <span className="truncate">{folder.name}</span>
              <span className="muted small">{folder.reference_count || ""}</span>
            </button>
          ))}

          {mayEdit && <NewFolder onAdded={() => folders.reload()} />}
        </aside>

        <div className="library-list">
          {references.loading ? (
            <Loading rows={6} />
          ) : references.error ? (
            <ErrorNote message={references.error} onRetry={references.reload} />
          ) : rows.length === 0 ? (
            <Empty title={search || folderId || type ? "Nothing matches" : "The library is empty"}>
              {search || folderId || type
                ? "Try a broader search, or choose Everything on the left."
                : "Import a .bib file from whatever you keep your bibliography in, or add a reference by hand."}
            </Empty>
          ) : (
            <ul className="reference-list">
              {rows.map((row) => (
                <li key={row.id}>
                  <button
                    type="button"
                    className={`reference ${openId === row.id ? "chosen" : ""}`}
                    onClick={() => setOpenId(row.id === openId ? null : row.id)}
                  >
                    <span className="reference-title">{row.title}</span>
                    <span className="reference-line muted small">{row.label}</span>
                    <span className="reference-marks">
                      <span className="badge">{humanise(row.reference_type)}</span>
                      {row.link_count > 0 && (
                        <span className="badge badge-ok" title="Attached to records">
                          {row.link_count} record{row.link_count === 1 ? "" : "s"}
                        </span>
                      )}
                      {(row.keywords ?? []).slice(0, 3).map((word) => (
                        <span key={word} className="badge">
                          {word}
                        </span>
                      ))}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}

          {references.data && references.data.total > PAGE && (
            <div className="row-tight" style={{ justifyContent: "center", marginTop: 12 }}>
              <button
                type="button"
                className="btn btn-sm"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE))}
              >
                Previous
              </button>
              <span className="muted small">
                {offset + 1}–{Math.min(offset + PAGE, references.data.total)} of{" "}
                {references.data.total}
              </span>
              <button
                type="button"
                className="btn btn-sm"
                disabled={offset + PAGE >= references.data.total}
                onClick={() => setOffset(offset + PAGE)}
              >
                Next
              </button>
            </div>
          )}
        </div>

        <aside className="library-detail">
          {open ? (
            <ReferencePanel reference={open} mayEdit={mayEdit} onChanged={refresh} />
          ) : (
            <p className="muted small">Choose a reference to see it.</p>
          )}
        </aside>
      </div>
    </>
  );
}

/* --------------------------------------------------------------------------
 * One reference
 * ----------------------------------------------------------------------- */
function ReferencePanel({
  reference,
  mayEdit,
  onChanged,
}: {
  reference: Reference;
  mayEdit: boolean;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const links = useQuery<RefLink[]>(
    (signal) => api.get(`/library/references/${reference.id}/links`, undefined, signal),
    [reference.id],
  );

  const remove = useAction(async () => {
    await api.delete(`/library/references/${reference.id}`);
    onChanged();
  });

  if (editing) {
    return (
      <EditReference
        reference={reference}
        folders={[]}
        inline
        onClose={() => setEditing(false)}
        onSaved={() => {
          setEditing(false);
          onChanged();
        }}
      />
    );
  }

  return (
    <>
      <div className="overline">{humanise(reference.reference_type)}</div>
      <h2 className="detail-title">{reference.title}</h2>
      <p className="muted small">{reference.label}</p>

      {reference.doi && (
        <p className="small">
          <span className="muted">DOI </span>
          <a href={`https://doi.org/${reference.doi}`} target="_blank" rel="noreferrer">
            {reference.doi}
          </a>
        </p>
      )}
      {reference.url && (
        <p className="small truncate">
          <a href={reference.url} target="_blank" rel="noreferrer">
            {reference.url}
          </a>
        </p>
      )}

      {reference.abstract && <p className="small">{reference.abstract}</p>}
      {reference.notes && (
        <div className="note-block">
          <div className="overline">Notes</div>
          <p className="small" style={{ marginBottom: 0 }}>
            {reference.notes}
          </p>
        </div>
      )}

      {/* The part a reference manager cannot do. */}
      <div className="overline" style={{ marginTop: 20 }}>
        What it is about
      </div>
      {links.loading ? (
        <Loading rows={1} />
      ) : (links.data ?? []).length === 0 ? (
        <p className="muted small">
          Not attached to anything yet. Attach it from a site, find or object&rsquo;s own page, and
          say which pages — that is what turns a bibliography into a finding aid.
        </p>
      ) : (
        <ul className="link-list">
          {(links.data ?? []).map((link) => (
            <li key={link.id}>
              <span className="badge">{link.target_kind}</span>{" "}
              {link.site_id ? (
                <Link to={`/sites/${link.site_id}`}>{link.target_label}</Link>
              ) : link.artifact_id ? (
                <Link to={`/artifacts/${link.artifact_id}`}>{link.target_label}</Link>
              ) : link.museum_object_id ? (
                <Link to={`/museum/objects/${link.museum_object_id}`}>{link.target_label}</Link>
              ) : link.project_id ? (
                <Link to={`/projects/${link.project_id}`}>{link.target_label}</Link>
              ) : (
                <span>{link.target_label}</span>
              )}
              {link.locator && <span className="mono small"> · {link.locator}</span>}
              {link.note && <div className="muted small">{link.note}</div>}
              {mayEdit && (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={async () => {
                    await api.delete(`/library/links/${link.id}`);
                    links.reload();
                    onChanged();
                  }}
                >
                  Detach
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {mayEdit && (
        <div className="row-tight" style={{ marginTop: 20 }}>
          <button type="button" className="btn btn-sm" onClick={() => setEditing(true)}>
            Edit
          </button>
          <button
            type="button"
            className="btn btn-danger btn-sm"
            onClick={() => void remove.run()}
            disabled={remove.running}
          >
            Remove
          </button>
        </div>
      )}
      {remove.error && <ErrorNote message={remove.error} />}
    </>
  );
}

/* --------------------------------------------------------------------------
 * Adding and editing
 * ----------------------------------------------------------------------- */
function EditReference({
  reference,
  folders,
  inline = false,
  onClose,
  onSaved,
}: {
  reference?: Reference;
  folders: Folder[];
  inline?: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    reference_type: reference?.reference_type ?? "article",
    title: reference?.title ?? "",
    authors: reference?.authors ?? "",
    year: reference?.year ? String(reference.year) : "",
    journal: reference?.journal ?? "",
    volume: reference?.volume ?? "",
    pages: reference?.pages ?? "",
    publisher: reference?.publisher ?? "",
    place: reference?.place ?? "",
    doi: reference?.doi ?? "",
    url: reference?.url ?? "",
    keywords: (reference?.keywords ?? []).join(", "),
    notes: reference?.notes ?? "",
  });
  const [chosen, setChosen] = useState<string[]>(reference?.collection_ids ?? []);

  const set = (key: keyof typeof form, value: string) =>
    setForm((current) => ({ ...current, [key]: value }));

  const save = useAction(async () => {
    const body: Record<string, unknown> = {
      ...form,
      year: form.year ? Number(form.year) : null,
      keywords: form.keywords
        ? form.keywords.split(",").map((word) => word.trim()).filter(Boolean)
        : [],
    };
    for (const key of Object.keys(body)) {
      if (body[key] === "") body[key] = null;
    }
    if (!reference) body.collection_ids = chosen;

    if (reference) await api.patch(`/library/references/${reference.id}`, body);
    else await api.post("/library/references", body);
    onSaved();
  });

  const field = (key: keyof typeof form, label: string, span = 6) => (
    <div className="form-cell" style={{ gridColumn: `span ${span}` }}>
      <div className="form-label">{label}</div>
      <input className="input" value={form[key]} onChange={(event) => set(key, event.target.value)} />
    </div>
  );

  return (
    <section className={inline ? "" : "card"} style={inline ? undefined : { marginBottom: 16 }}>
      <div className={inline ? "" : "card-body"}>
        <div className="overline" style={{ marginBottom: 10 }}>
          {reference ? "Edit reference" : "Add a reference"}
        </div>

        <div className="form-grid">
          <div className="form-cell" style={{ gridColumn: "span 4" }}>
            <div className="form-label">Kind</div>
            <select
              className="input"
              value={form.reference_type}
              onChange={(event) => set("reference_type", event.target.value)}
            >
              {TYPES.map((value) => (
                <option key={value} value={value}>
                  {humanise(value)}
                </option>
              ))}
            </select>
          </div>
          <div className="form-cell" style={{ gridColumn: "span 8" }}>
            <div className="form-label">
              Title <span className="required">*</span>
            </div>
            <input
              className="input"
              value={form.title}
              onChange={(event) => set("title", event.target.value)}
            />
          </div>

          {field("authors", "Authors", 8)}
          {field("year", "Year", 4)}
          {field("journal", "Journal, or the book it is in", 8)}
          {field("volume", "Volume", 2)}
          {field("pages", "Pages", 2)}
          {field("publisher", "Publisher", 6)}
          {field("place", "Place", 6)}
          {field("doi", "DOI", 6)}
          {field("url", "URL", 6)}
          {field("keywords", "Keywords, comma separated", 12)}

          <div className="form-cell" style={{ gridColumn: "span 12" }}>
            <div className="form-label">Notes</div>
            <textarea
              className="input"
              rows={3}
              value={form.notes}
              onChange={(event) => set("notes", event.target.value)}
            />
          </div>

          {!reference && folders.length > 0 && (
            <div className="form-cell" style={{ gridColumn: "span 12" }}>
              <div className="form-label">Folders</div>
              <div className="row-tight wrap">
                {folders.map((folder) => (
                  <label key={folder.id} className="chip-check">
                    <input
                      type="checkbox"
                      checked={chosen.includes(folder.id)}
                      onChange={(event) =>
                        setChosen((current) =>
                          event.target.checked
                            ? [...current, folder.id]
                            : current.filter((id) => id !== folder.id),
                        )
                      }
                    />
                    {folder.name}
                  </label>
                ))}
              </div>
            </div>
          )}
        </div>

        {save.error && <ErrorNote message={save.error} />}

        <div className="row-tight" style={{ marginTop: 12 }}>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={!form.title.trim() || save.running}
            onClick={() => void save.run()}
          >
            {save.running ? "Saving…" : "Save"}
          </button>
          <button type="button" className="btn btn-sm" onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </section>
  );
}

function NewFolder({ onAdded }: { onAdded: () => void }) {
  const [name, setName] = useState("");
  const [open, setOpen] = useState(false);

  const save = useAction(async () => {
    await api.post("/library/collections", { name });
    setName("");
    setOpen(false);
    onAdded();
  });

  if (!open) {
    return (
      <button type="button" className="folder-item muted" onClick={() => setOpen(true)}>
        + New folder
      </button>
    );
  }

  return (
    <div style={{ padding: "6px 8px" }}>
      <input
        className="input input-sm"
        autoFocus
        value={name}
        placeholder="Folder name"
        onChange={(event) => setName(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && name.trim()) void save.run();
          if (event.key === "Escape") setOpen(false);
        }}
      />
      {save.error && <ErrorNote message={save.error} />}
    </div>
  );
}

/* --------------------------------------------------------------------------
 * Importing
 * ----------------------------------------------------------------------- */
function ImportBib({
  folders,
  onClose,
  onDone,
}: {
  folders: Folder[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [folderId, setFolderId] = useState("");
  const [preview, setPreview] = useState<{
    parsed: number;
    duplicates: number;
    new: number;
    problems: string[];
  } | null>(null);

  const check = useAction(async (chosen: File) => {
    setPreview(await api.upload("/library/import/preview", chosen));
  });

  const run = useAction(async () => {
    if (!file) return;
    await api.upload(
      `/library/import${folderId ? `?collection_id=${folderId}` : ""}`,
      file,
    );
    onDone();
  });

  return (
    <section className="card" style={{ marginBottom: 16 }}>
      <div className="card-body">
        <div className="overline" style={{ marginBottom: 8 }}>
          Import BibTeX
        </div>
        <p className="muted small">
          A <span className="mono">.bib</span> file exported from Zotero, Mendeley, EndNote or
          anything else. Nothing is added until you have seen what it holds — and importing the same
          file twice adds nothing the second time.
        </p>

        <div className="row-tight wrap">
          <input
            type="file"
            accept=".bib,text/plain"
            onChange={(event) => {
              const chosen = event.target.files?.[0] ?? null;
              setFile(chosen);
              setPreview(null);
              if (chosen) void check.run(chosen);
            }}
          />
          {folders.length > 0 && (
            <select
              className="input input-sm"
              value={folderId}
              onChange={(event) => setFolderId(event.target.value)}
            >
              <option value="">No folder</option>
              {folders.map((folder) => (
                <option key={folder.id} value={folder.id}>
                  File into {folder.name}
                </option>
              ))}
            </select>
          )}
        </div>

        {check.running && <Loading rows={1} label="Reading the file" />}
        {check.error && <ErrorNote message={check.error} />}

        {preview && (
          <div className="alert" style={{ marginTop: 12 }}>
            <span>
              <b>{preview.parsed}</b> references read. <b>{preview.new}</b> would be added
              {preview.duplicates > 0 && `, ${preview.duplicates} already in the library`}.
              {preview.problems.map((problem) => (
                <div key={problem} className="muted small">
                  {problem}
                </div>
              ))}
            </span>
          </div>
        )}

        {run.error && <ErrorNote message={run.error} />}

        <div className="row-tight" style={{ marginTop: 12 }}>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={!preview || preview.new === 0 || run.running}
            onClick={() => void run.run()}
          >
            {run.running ? "Importing…" : preview ? `Add ${preview.new}` : "Add"}
          </button>
          <button type="button" className="btn btn-sm" onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </section>
  );
}
