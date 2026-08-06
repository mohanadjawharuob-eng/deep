/**
 * What has been published about this record.
 *
 * The other half of the library, and the half that makes it worth having: a
 * reference attached to a site is a bibliography entry, and the same reference
 * attached to context 1042 at pages 88-91 is a finding aid. Somebody re-opening
 * the archive in ten years needs the second.
 *
 * Attaching is deliberately a search over the library rather than a form. A
 * reference typed in from here would be a second copy of one already filed,
 * and two copies of a citation is how a bibliography stops being usable.
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import { useAction, useDebounced, useQuery, useSession } from "../lib/hooks";
import { ErrorNote, Loading } from "./ui";

type Target = {
  project_id?: string;
  site_id?: string;
  context_id?: string;
  artifact_id?: string;
  museum_object_id?: string;
};

type RefLink = {
  id: string;
  locator?: string | null;
  note?: string | null;
  reference?: { id: string; title: string; label: string } | null;
};

type Found = { id: string; title: string; label: string };

export function References({
  target,
  module = "archaeology",
}: {
  target: Target;
  /** Which module's contributor level may attach. */
  module?: "archaeology" | "museum";
}) {
  const { can } = useSession();
  const mayEdit = can(module, "contributor");
  const [attaching, setAttaching] = useState(false);

  const key = Object.values(target).find(Boolean) ?? "";
  const links = useQuery<RefLink[]>(
    (signal) => api.get("/library/for-record", target, signal),
    [key],
  );

  const rows = links.data ?? [];

  return (
    <section className="card" style={{ marginTop: 16 }}>
      <div className="card-header">
        <span className="card-title">Published in</span>
        {mayEdit && !attaching && (
          <button type="button" className="btn btn-sm" onClick={() => setAttaching(true)}>
            Attach a reference…
          </button>
        )}
      </div>

      <div className="card-body">
        {attaching && (
          <Attach
            target={target}
            onClose={() => setAttaching(false)}
            onAttached={() => {
              setAttaching(false);
              links.reload();
            }}
          />
        )}

        {links.loading ? (
          <Loading rows={1} />
        ) : links.error ? (
          <ErrorNote message={links.error} onRetry={links.reload} />
        ) : rows.length === 0 ? (
          <p className="muted small" style={{ marginBottom: 0 }}>
            Nothing yet. Attach a reference from the library and say which pages — that is what
            makes it findable rather than merely listed.
          </p>
        ) : (
          <ul className="link-list">
            {rows.map((link) => (
              <li key={link.id}>
                <div>
                  <Link to="/library">{link.reference?.title ?? "Reference"}</Link>
                  {link.locator && <span className="mono small"> · {link.locator}</span>}
                </div>
                <div className="muted small">{link.reference?.label}</div>
                {link.note && <div className="muted small">{link.note}</div>}
                {mayEdit && (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={async () => {
                      await api.delete(`/library/links/${link.id}`);
                      links.reload();
                    }}
                  >
                    Detach
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function Attach({
  target,
  onClose,
  onAttached,
}: {
  target: Target;
  onClose: () => void;
  onAttached: () => void;
}) {
  const [term, setTerm] = useState("");
  const search = useDebounced(term);
  const [chosen, setChosen] = useState<Found | null>(null);
  const [locator, setLocator] = useState("");
  const [note, setNote] = useState("");

  const found = useQuery<{ items: Found[] }>(
    (signal) =>
      search
        ? api.get("/library/references", { q: search, limit: 8 }, signal)
        : Promise.resolve({ items: [] }),
    [search],
  );

  const save = useAction(async () => {
    if (!chosen) return;
    await api.post(`/library/references/${chosen.id}/links`, {
      ...target,
      locator: locator || undefined,
      note: note || undefined,
    });
    onAttached();
  });

  return (
    <div className="inset-form">
      {chosen ? (
        <>
          <div className="strong">{chosen.title}</div>
          <div className="muted small" style={{ marginBottom: 10 }}>
            {chosen.label}
          </div>

          <div className="form-grid">
            <div className="form-cell" style={{ gridColumn: "span 4" }}>
              <div className="form-label">Where in it</div>
              <input
                className="input"
                value={locator}
                maxLength={120}
                placeholder="88-91, fig. 14, pl. IIIa"
                onChange={(event) => setLocator(event.target.value)}
              />
              <div className="form-help">
                The point of this. Without it the attachment is a bibliography entry; with it, it
                is a finding aid.
              </div>
            </div>
            <div className="form-cell" style={{ gridColumn: "span 8" }}>
              <div className="form-label">Why it matters here</div>
              <input
                className="input"
                value={note}
                placeholder="First publication; reinterprets the sequence; the parallel"
                onChange={(event) => setNote(event.target.value)}
              />
            </div>
          </div>

          {save.error && <ErrorNote message={save.error} />}

          <div className="row-tight" style={{ marginTop: 10 }}>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => void save.run()}
              disabled={save.running}
            >
              {save.running ? "Attaching…" : "Attach"}
            </button>
            <button type="button" className="btn btn-sm" onClick={() => setChosen(null)}>
              Choose another
            </button>
            <button type="button" className="btn btn-sm" onClick={onClose}>
              Cancel
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="form-label">Search the library</div>
          <input
            className="input"
            autoFocus
            value={term}
            placeholder="Title, author, journal…"
            onChange={(event) => setTerm(event.target.value)}
          />

          {search && found.data && found.data.items.length === 0 && (
            <p className="muted small" style={{ marginTop: 8 }}>
              Nothing matches. Add it to the <Link to="/library">library</Link> first — a reference
              typed in from here would be a second copy of one already filed.
            </p>
          )}

          <ul className="reference-list" style={{ marginTop: 8 }}>
            {(found.data?.items ?? []).map((item) => (
              <li key={item.id}>
                <button type="button" className="reference" onClick={() => setChosen(item)}>
                  <span className="reference-title">{item.title}</span>
                  <span className="reference-line muted small">{item.label}</span>
                </button>
              </li>
            ))}
          </ul>

          <button type="button" className="btn btn-sm" onClick={onClose}>
            Cancel
          </button>
        </>
      )}
    </div>
  );
}
