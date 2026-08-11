/**
 * The photographs on a record, and how one more gets there.
 *
 * "Where are my photos?" was a fair question with a bad answer: a photograph
 * uploaded to a site was stored, checksummed, thumbnailed, permission-checked
 * — and then shown on no screen anywhere. It existed in the archive and not in
 * the interface, which from where anybody is sitting is the same as not
 * existing.
 *
 * So every record that can hold photographs shows them, in the one place
 * somebody would look: on the record. The strip is deliberately plain — a grid
 * of thumbnails, a count, and a button — because the interesting thing about a
 * site photograph is the site, and a gallery that competes with the record it
 * belongs to is a gallery in the wrong place.
 *
 * Uploads are one at a time and reported one at a time. A batch that fails as
 * a unit tells somebody with ten photographs and one bad one that nothing
 * worked, which is both untrue and unhelpful.
 */

import { useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api, type Page } from "../lib/api";
import { useAction, useQuery, useSession } from "../lib/hooks";
import { AuthImage, ErrorNote, Loading } from "./ui";
import { PhotoViewer } from "./PhotoViewer";

export type Parent = {
  project_id?: string;
  site_id?: string;
  artifact_id?: string;
  context_id?: string;
  museum_object_id?: string;
  /**
   * A collection is not something a photograph attaches to — it is a place
   * to look. Passing one shows the photographs of every object in it, and
   * there is nothing to upload here, because there is no one record for an
   * uploaded picture to belong to.
   */
  collection_id?: string;
};

export type PhotoRow = {
  id: string;
  title: string;
  description?: string | null;
  photographer?: string | null;
  taken_at?: string | null;
  created_at: string;
  review_status?: string;
  site_id?: string | null;
  artifact_id?: string | null;
  context_id?: string | null;
  museum_object_id?: string | null;
};

/** Which record a picture is of, when the strip is showing more than one. */
function recordOf(photo: PhotoRow): { to: string; label: string } | null {
  if (photo.museum_object_id) {
    return { to: `/museum/objects/${photo.museum_object_id}`, label: "an object" };
  }
  if (photo.artifact_id) return { to: `/artifacts/${photo.artifact_id}`, label: "a find" };
  if (photo.context_id) return { to: `/contexts/${photo.context_id}`, label: "a context" };
  if (photo.site_id) return { to: `/sites/${photo.site_id}`, label: "the site" };
  return null;
}

export function RecordPhotos({
  parent,
  /** Which module governs adding one. A museum object is the museum's. */
  module = "archaeology",
  title = "Photographs",
  /**
   * How the count reads — "on this site and its finds", "in this collection".
   *
   * A site's photographs already include the ones taken of the finds dug out
   * of it, because an upload against a find records the site too. Saying "12
   * on this record" over a strip that is mostly finds is the count being
   * quietly wrong about what it counted.
   */
  counted = "on this record",
}: {
  parent: Parent;
  module?: "archaeology" | "museum";
  title?: string;
  counted?: string;
}) {
  const { can } = useSession();
  const mayAdd = can(module, "contributor") && !parent.collection_id;
  const chooser = useRef<HTMLInputElement>(null);
  const [failures, setFailures] = useState<string[]>([]);
  const [viewing, setViewing] = useState<PhotoRow | null>(null);

  const key = Object.values(parent).find(Boolean) ?? "";
  const photos = useQuery<Page<PhotoRow>>(
    (signal) => api.get("/photographs", { ...parent, limit: 60 }, signal),
    [key],
  );

  const send = useAction(async (files: File[]) => {
    const failed: string[] = [];
    for (const file of files) {
      try {
        await api.upload("/photographs", file, { ...parent, title: file.name });
      } catch (error) {
        failed.push(`${file.name}: ${error instanceof Error ? error.message : "could not be sent"}`);
      }
    }
    setFailures(failed);
    photos.reload();
  });

  const rows = photos.data?.items ?? [];

  return (
    <section className="card" style={{ marginTop: 16 }}>
      <div className="card-header">
        <span className="card-title">{title}</span>
        <span className="muted small">
          {photos.data?.total
            ? `${photos.data.total} ${counted}`
            : photos.loading
              ? ""
              : "none yet"}
        </span>
      </div>

      <div className="card-body">
        {photos.loading ? (
          <Loading rows={2} />
        ) : photos.error ? (
          <ErrorNote message={photos.error} onRetry={photos.reload} />
        ) : rows.length === 0 ? (
          <p className="muted small" style={{ margin: 0 }}>
            No photographs yet.
          </p>
        ) : (
          <div className="photo-strip">
            {rows.map((photo) => (
              <figure key={photo.id} className="photo-tile">
                <button
                  type="button"
                  className="pick-target"
                  onClick={() => setViewing(photo)}
                  aria-label={`Open ${photo.title}`}
                >
                  <AuthImage
                    path={`/photographs/${photo.id}/thumbnail`}
                    query={{ size: 400 }}
                    alt={photo.title}
                    fallback={<span className="small muted">could not load</span>}
                  />
                </button>
                <figcaption className="truncate" title={photo.title}>
                  {photo.title}
                  {/* A site's strip mixes trench shots with pictures of the
                      finds. Saying which record each is on is the difference
                      between a useful wall and a wall of unlabelled
                      thumbnails. */}
                  {!parent.artifact_id && !parent.museum_object_id && recordOf(photo) && (
                    <>
                      {" "}
                      <Link className="small" to={recordOf(photo)!.to}>
                        {recordOf(photo)!.label}
                      </Link>
                    </>
                  )}
                  {/* Arrived from outside, or from somebody whose work is
                      reviewed: said out loud rather than shown as settled. */}
                  {photo.review_status === "pending" && (
                    <span className="badge badge-warning" style={{ marginLeft: 4 }}>
                      unreviewed
                    </span>
                  )}
                </figcaption>
              </figure>
            ))}
          </div>
        )}

        {failures.length > 0 && (
          <div className="alert alert-warning small" style={{ marginTop: 10 }}>
            <b>
              {failures.length} file{failures.length === 1 ? "" : "s"} could not be added.
            </b>
            <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
              {failures.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
        )}
        {send.error && <ErrorNote message={send.error} />}

        {mayAdd && (
          <div className="row-tight" style={{ marginTop: 10 }}>
            <button
              type="button"
              className="btn btn-sm"
              disabled={send.running}
              onClick={() => chooser.current?.click()}
            >
              {send.running ? "Adding…" : "Add photographs…"}
            </button>
            <span className="muted small">
              Several at once is fine. Each is reported on its own.
            </span>
            <input
              ref={chooser}
              type="file"
              accept="image/*"
              multiple
              hidden
              onChange={(event) => {
                const files = Array.from(event.target.files ?? []);
                if (files.length) void send.run(files);
                event.target.value = "";
              }}
            />
          </div>
        )}
      </div>

      {viewing && (
        <PhotoViewer
          photo={viewing}
          onClose={() => setViewing(null)}
          onChanged={() => photos.reload()}
        />
      )}
    </section>
  );
}
