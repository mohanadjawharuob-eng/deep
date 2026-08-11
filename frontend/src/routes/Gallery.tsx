/**
 * Every photograph, in one place.
 *
 * The record panels answer "what pictures does this find have". They do not
 * answer "what have we got", which is the question somebody asks when they
 * want to know whether the season was photographed, or which of four thousand
 * objects still has no picture, or simply where the thing they uploaded went.
 *
 * So: a wall of them, newest first, with the record each belongs to written
 * underneath. The caption is the point as much as the picture — a gallery of
 * unattributed images is a screensaver, and this is an archive.
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import { api, type Page } from "../lib/api";
import { useDebounced, useQuery } from "../lib/hooks";
import { AuthImage, Empty, ErrorNote, Loading, PageHeader, formatDate } from "../components/ui";

type Photo = {
  id: string;
  title: string;
  description?: string | null;
  photographer?: string | null;
  taken_at?: string | null;
  created_at: string;
  review_status?: string;
  project_id?: string | null;
  site_id?: string | null;
  artifact_id?: string | null;
  context_id?: string | null;
  museum_object_id?: string | null;
};

const PER_PAGE = 48;

/** Where a photograph came from, deepest link first — the most specific one
    is the one worth showing. */
function belongsTo(photo: Photo): { to: string; label: string } | null {
  if (photo.museum_object_id) {
    return { to: `/museum/objects/${photo.museum_object_id}`, label: "museum object" };
  }
  if (photo.artifact_id) return { to: `/artifacts/${photo.artifact_id}`, label: "find" };
  if (photo.site_id) return { to: `/sites/${photo.site_id}`, label: "site" };
  if (photo.project_id) return { to: `/projects/${photo.project_id}`, label: "project" };
  return null;
}

export function Gallery() {
  const [term, setTerm] = useState("");
  const search = useDebounced(term);
  const [unreviewed, setUnreviewed] = useState(false);
  const [offset, setOffset] = useState(0);

  const photos = useQuery<Page<Photo>>(
    (signal) =>
      api.get(
        "/photographs",
        {
          q: search || undefined,
          review_status: unreviewed ? "pending" : undefined,
          limit: PER_PAGE,
          offset,
        },
        signal,
      ),
    [search, unreviewed, offset],
  );

  const rows = photos.data?.items ?? [];
  const total = photos.data?.total ?? 0;

  return (
    <div>
      <PageHeader
        title="Photographs"
        subtitle="Everything that has been uploaded, newest first, and what each one is of."
      />

      <div className="toolbar">
        <input
          className="input"
          style={{ maxWidth: "22rem" }}
          value={term}
          placeholder="Title, description, tag…"
          onChange={(event) => {
            setTerm(event.target.value);
            setOffset(0);
          }}
        />
        <label className="chip-check">
          <input
            type="checkbox"
            checked={unreviewed}
            onChange={(event) => {
              setUnreviewed(event.target.checked);
              setOffset(0);
            }}
          />
          Waiting for review
        </label>
        {total > 0 && (
          <span className="muted small">
            {total} photograph{total === 1 ? "" : "s"}
          </span>
        )}
      </div>

      {photos.loading ? (
        <Loading rows={4} />
      ) : photos.error ? (
        <ErrorNote message={photos.error} onRetry={photos.reload} />
      ) : rows.length === 0 ? (
        <Empty title={search || unreviewed ? "Nothing matches" : "No photographs yet"}>
          {search || unreviewed
            ? "Try a different word, or clear the filters."
            : "Open a site, a find or a museum object and use “Add photographs”. Every picture belongs to a record."}
        </Empty>
      ) : (
        <>
          <div className="gallery">
            {rows.map((photo) => {
              const origin = belongsTo(photo);
              return (
                <figure key={photo.id} className="gallery-tile">
                  <AuthImage
                    path={`/photographs/${photo.id}/thumbnail`}
                    query={{ size: 600 }}
                    alt={photo.title}
                    fallback={<span className="small muted">could not load</span>}
                  />
                  <figcaption>
                    <span className="strong truncate" title={photo.title}>
                      {photo.title}
                    </span>
                    <span className="muted small">
                      {/* Which record, as a link. A gallery of unattributed
                          images is a screensaver; this is an archive. */}
                      {origin ? (
                        <Link to={origin.to}>on a {origin.label}</Link>
                      ) : (
                        "not attached to a record"
                      )}
                      {" · "}
                      {formatDate(photo.taken_at ?? photo.created_at)}
                    </span>
                    {photo.review_status === "pending" && (
                      <span className="badge badge-warning">unreviewed</span>
                    )}
                  </figcaption>
                </figure>
              );
            })}
          </div>

          <div className="pager">
            <button
              type="button"
              className="btn btn-sm"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PER_PAGE))}
            >
              Newer
            </button>
            <span className="muted small">
              {offset + 1}–{Math.min(offset + PER_PAGE, total)} of {total}
            </span>
            <button
              type="button"
              className="btn btn-sm"
              disabled={offset + PER_PAGE >= total}
              onClick={() => setOffset(offset + PER_PAGE)}
            >
              Older
            </button>
          </div>
        </>
      )}
    </div>
  );
}

export default Gallery;
