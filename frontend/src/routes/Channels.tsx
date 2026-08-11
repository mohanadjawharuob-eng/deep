/**
 * Facebook and Instagram, and the pictures kept for each.
 *
 * The old screen asked you to invent a "channel" — a record with a name, a
 * platform, a handle — and then showed you nothing, because a channel with no
 * posts in it is an empty box you filled in a form to create. Two institutions
 * out of two have the same two accounts, so they are simply here.
 *
 * A channel is a **folder**, in the same tree as everything else in Media.
 * That is the whole simplification: no second idea of a folder, no separate
 * place a photograph can hide. Putting a picture in Instagram / September is
 * filing, and unfiling it puts it back where it was.
 */

import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import { useAction, useQuery, useSession } from "../lib/hooks";
import { ErrorNote, Loading, PageHeader } from "../components/ui";
import { Media, type Folder } from "./Media";

const CHANNELS = [
  {
    kind: "facebook" as const,
    name: "Facebook",
    // The f, drawn rather than fetched: no logo files, no CDN, no trademark
    // sitting in the repository.
    path: "M13 5h-1.6C10.6 5 10 5.6 10 6.4V8h3l-.4 3H10v6H7v-6H5V8h2V6.2C7 4 8.4 2.6 10.6 2.6c.9 0 1.7.1 2.4.2z",
  },
  {
    kind: "instagram" as const,
    name: "Instagram",
    path: "M6 3.5h8a2.5 2.5 0 0 1 2.5 2.5v8a2.5 2.5 0 0 1-2.5 2.5H6A2.5 2.5 0 0 1 3.5 14V6A2.5 2.5 0 0 1 6 3.5Zm4 3.6a2.9 2.9 0 1 0 0 5.8 2.9 2.9 0 0 0 0-5.8Zm4.1-.9v.01",
  },
];

export function Channels() {
  const { can } = useSession();
  const mayEdit = can("social_media", "contributor");
  const [chosen, setChosen] = useState<(typeof CHANNELS)[number]["kind"] | null>(null);

  const folders = useQuery<Folder[]>((signal) => api.get("/folders", undefined, signal), []);
  const all = useMemo(() => folders.data ?? [], [folders.data]);

  /** Which channels already have a folder, and which have to be made. */
  const roots = useMemo(
    () =>
      Object.fromEntries(
        CHANNELS.map((channel) => [
          channel.kind,
          all.find((folder) => folder.kind === channel.kind && folder.parent_id === null) ?? null,
        ]),
      ),
    [all],
  );

  // Made on first sight rather than by a form. Nobody should have to fill in a
  // record to say that their museum is on Instagram.
  const ensure = useAction(async (kind: string, name: string) => {
    await api.post("/folders", { name, kind });
    folders.reload();
  });

  useEffect(() => {
    if (folders.loading || !mayEdit) return;
    const missing = CHANNELS.find((channel) => !roots[channel.kind]);
    if (missing && !ensure.running) void ensure.run(missing.kind, missing.name);
  }, [folders.loading, roots, mayEdit, ensure.running]);

  if (folders.loading) return <Loading rows={4} />;

  if (chosen) {
    const channel = CHANNELS.find((item) => item.kind === chosen)!;
    return (
      <div>
        <div className="row-tight" style={{ marginBottom: 12 }}>
          <button type="button" className="btn btn-sm" onClick={() => setChosen(null)}>
            ← Both channels
          </button>
          {mayEdit && (
            <Link className="btn btn-sm btn-primary" to={`/social/posts/new?platform=${channel.kind}`}>
              Write a {channel.name} post
            </Link>
          )}
          <Link className="btn btn-sm" to={`/social?platform=${channel.kind}`}>
            What has gone out
          </Link>
        </div>
        <Media
          onlyKind={channel.kind}
          title={channel.name}
          subtitle="Folders and pictures kept for this channel. They are the same photographs as everywhere else — filed, not copied."
        />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Channels"
        subtitle="Where things get posted, and the pictures kept ready for each."
      />

      {ensure.error && <ErrorNote message={ensure.error} />}

      <div className="channel-grid">
        {CHANNELS.map((channel) => {
          const folder = roots[channel.kind];
          const inside = all.filter((item) => item.parent_id === folder?.id).length;
          return (
            <div key={channel.kind} className="channel-slot">
            <button
              type="button"
              className={`channel-card channel-${channel.kind}`}
              onClick={() => setChosen(channel.kind)}
            >
              <svg viewBox="0 0 20 20" width="30" height="30" aria-hidden="true">
                <path
                  d={channel.path}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.4"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              <span className="channel-name">{channel.name}</span>
              <span className="muted small">
                {folder
                  ? `${folder.file_count} picture${folder.file_count === 1 ? "" : "s"}` +
                    (inside ? ` · ${inside} folder${inside === 1 ? "" : "s"}` : "")
                  : "setting up…"}
              </span>
            </button>
            {mayEdit && (
              <Link
                className="btn btn-sm"
                to={`/social/posts/new?platform=${channel.kind}`}
              >
                Create post
              </Link>
            )}
            </div>
          );
        })}
      </div>

      <p className="muted small" style={{ marginTop: 20, maxWidth: "34rem" }}>
        These are folders in the media library, not a separate place. A picture put
        in one is <b>filed, not copied</b> — it is the same photograph, still on the
        record it belongs to, and taking it out of the channel leaves it there.
      </p>
    </div>
  );
}

export default Channels;
