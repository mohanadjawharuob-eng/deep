/**
 * Writing a post, in the shape the channel it is going to actually wants.
 *
 * Writing for Instagram is not writing for Facebook. A caption sits under a
 * picture and cannot carry a tappable link; a Facebook post is text that may
 * have a link and may have no picture at all. One "post" form that ignores the
 * difference produces drafts that cannot be posted as written, and whoever has
 * to publish them ends up rewriting every one — which is exactly the work the
 * platform was supposed to save.
 *
 * The differences are **served, not hard-coded here**: `/social/composers`
 * says what each channel calls its writing, how long it may be, whether a
 * picture is the point, whether a link works. Same reason form layouts are
 * served — they are conventions, they change when the platforms change, and
 * they should change in one place.
 *
 * Every limit is advisory. The counter goes red and the button stays enabled,
 * because this platform does not publish anything and is in no position to
 * refuse. What it can usefully do is tell you before you paste it somewhere
 * that will.
 */

import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { api, type Page, type SocialAccount } from "../lib/api";
import { useAction, useQuery, useSession } from "../lib/hooks";
import { AuthImage, Empty, ErrorNote, Loading, PageHeader, humanise } from "../components/ui";

type Composer = {
  platform: string;
  label: string;
  text_label: string;
  text_help: string;
  text_limit: number | null;
  needs_image: boolean;
  image_help: string;
  allows_link: boolean;
  link_help: string | null;
  kinds: string[];
  hashtag_help: string;
};

type PickablePhoto = { id: string; title: string };

export function NewPost() {
  const navigate = useNavigate();
  const { can } = useSession();
  const [params] = useSearchParams();
  const wanted = params.get("platform") ?? "instagram";

  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [kind, setKind] = useState("post");
  const [link, setLink] = useState("");
  const [tags, setTags] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);

  const composers = useQuery<Composer[]>(
    (signal) => api.get("/social/composers", undefined, signal),
    [],
  );
  const accounts = useQuery<Page<SocialAccount>>(
    (signal) => api.get("/social/accounts", { limit: 100 }, signal),
    [],
  );
  // The pictures already filed under this channel are the ones somebody put
  // there to be posted. Everything else in the archive is one screen away.
  const photos = useQuery<Page<PickablePhoto>>(
    (signal) => api.get("/photographs", { limit: 40, sort: "-created_at" }, signal),
    [],
  );

  const composer = useMemo(
    () => composers.data?.find((item) => item.platform === wanted),
    [composers.data, wanted],
  );
  const account = useMemo(
    () => accounts.data?.items.find((item) => item.platform === wanted),
    [accounts.data, wanted],
  );

  const makeAccount = useAction(async () => {
    await api.post("/social/accounts", {
      platform: wanted,
      handle: `our_${wanted}`,
      name: composer?.label ?? humanise(wanted),
    });
    accounts.reload();
  });

  const save = useAction(async () => {
    if (!account) return;
    const created = await api.post<{ id: string }>(
      `/social/accounts/${account.id}/posts`,
      {
        title: title.trim(),
        body: body.trim() || null,
        kind,
        hashtags: tags
          .split(/[\s,]+/)
          .map((tag) => tag.replace(/^#/, "").trim())
          .filter(Boolean),
        external_url: composer?.allows_link && link.trim() ? link.trim() : null,
      },
    );
    for (const [index, photographId] of chosen.entries()) {
      await api.post(`/social/posts/${created.id}/assets`, {
        photograph_id: photographId,
        position: index,
      });
    }
    navigate(`/social/posts/${created.id}`);
  });

  if (!can("social_media", "contributor")) {
    return (
      <Empty title="You can read the outreach record but not add to it">
        Writing on behalf of the institution needs contributor access to the social
        media module.
      </Empty>
    );
  }

  if (composers.loading || accounts.loading) return <Loading rows={6} />;
  if (!composer) {
    return <ErrorNote message={`No channel called ${wanted}`} onRetry={composers.reload} />;
  }

  const overLimit = composer.text_limit !== null && body.length > composer.text_limit;
  const missingImage = composer.needs_image && chosen.length === 0;

  return (
    <>
      <PageHeader
        breadcrumb={[
          { label: "Social media", to: "/social/accounts" },
          { label: composer.label, to: `/social/accounts?channel=${composer.platform}` },
          { label: "New post" },
        ]}
        title={`A post for ${composer.label}`}
        subtitle="Written here, checked by a colleague, then put up by hand — the platform holds no keys to your accounts."
      />

      {!account && (
        <div className="alert alert-info">
          <b>No {composer.label} account is recorded yet.</b> A post has to belong to one.
          <div className="row-tight" style={{ marginTop: 8 }}>
            <button
              type="button"
              className="btn btn-sm btn-primary"
              disabled={makeAccount.running}
              onClick={() => void makeAccount.run()}
            >
              {makeAccount.running ? "Adding…" : `Add our ${composer.label} account`}
            </button>
          </div>
          {makeAccount.error && <ErrorNote message={makeAccount.error} />}
        </div>
      )}

      <section className="card">
        <div className="card-body">
          <div className="form-grid">
            <label className="field form-cell" style={{ gridColumn: "span 8" }}>
              <span className="field-label">What is it about?</span>
              <input
                className="input"
                value={title}
                autoFocus
                placeholder="The painted jar from Trench 4"
                onChange={(event) => setTitle(event.target.value)}
              />
              <span className="field-help">
                For your own list, not for the public. A calendar of subjects reads better
                than a wall of opening sentences.
              </span>
            </label>

            <label className="field form-cell" style={{ gridColumn: "span 4" }}>
              <span className="field-label">Kind</span>
              <select
                className="input"
                value={kind}
                onChange={(event) => setKind(event.target.value)}
              >
                {composer.kinds.map((item) => (
                  <option key={item} value={item}>
                    {humanise(item)}
                  </option>
                ))}
              </select>
            </label>

            <label className="field form-cell" style={{ gridColumn: "span 12" }}>
              <span className="field-label">
                {composer.text_label}
                {composer.text_limit !== null && (
                  <span className={`count ${overLimit ? "over" : ""}`}>
                    {body.length.toLocaleString()} / {composer.text_limit.toLocaleString()}
                  </span>
                )}
              </span>
              <textarea
                className="input"
                rows={8}
                value={body}
                onChange={(event) => setBody(event.target.value)}
              />
              <span className="field-help">{composer.text_help}</span>
              {overLimit && (
                <span className="field-help" style={{ color: "var(--danger)" }}>
                  Longer than {composer.label} accepts. Nothing here stops you saving it —
                  but it will be cut when it goes up.
                </span>
              )}
            </label>

            <label className="field form-cell" style={{ gridColumn: "span 12" }}>
              <span className="field-label">Hashtags</span>
              <input
                className="input"
                value={tags}
                placeholder="#archaeology #telldemo"
                onChange={(event) => setTags(event.target.value)}
              />
              <span className="field-help">{composer.hashtag_help}</span>
            </label>

            {composer.allows_link ? (
              <label className="field form-cell" style={{ gridColumn: "span 12" }}>
                <span className="field-label">A link</span>
                <input
                  className="input"
                  value={link}
                  placeholder="https://…"
                  onChange={(event) => setLink(event.target.value)}
                />
                {composer.link_help && <span className="field-help">{composer.link_help}</span>}
              </label>
            ) : (
              composer.link_help && (
                <p
                  className="field-help form-cell"
                  style={{ gridColumn: "span 12", marginTop: 0 }}
                >
                  {composer.link_help}
                </p>
              )
            )}
          </div>
        </div>
      </section>

      <section className="card" style={{ marginTop: "var(--space-4)" }}>
        <div className="card-header">
          <span className="card-title">Pictures</span>
          <span className="muted small">
            {chosen.length} chosen{composer.needs_image ? " · at least one needed" : ""}
          </span>
        </div>
        <div className="card-body">
          <p className="small muted" style={{ marginTop: 0 }}>
            {composer.image_help} These are the photographs already in the archive — using
            one here records that it went out in public, which is what somebody needs to
            know before publishing it again.
          </p>

          {photos.loading ? (
            <Loading rows={2} />
          ) : photos.data?.items.length ? (
            <div className="gallery">
              {photos.data.items.map((photo) => {
                const picked = chosen.includes(photo.id);
                return (
                  <figure
                    key={photo.id}
                    className={`gallery-tile pickable ${picked ? "chosen" : ""}`}
                  >
                    <button
                      type="button"
                      className="pick-target"
                      aria-pressed={picked}
                      onClick={() =>
                        setChosen((current) =>
                          picked
                            ? current.filter((id) => id !== photo.id)
                            : [...current, photo.id],
                        )
                      }
                    >
                      <AuthImage
                        path={`/photographs/${photo.id}/thumbnail`}
                        query={{ size: 400 }}
                        alt={photo.title}
                        fallback={<span className="small muted">could not load</span>}
                      />
                    </button>
                    <figcaption className="truncate small" title={photo.title}>
                      {picked ? `${chosen.indexOf(photo.id) + 1}. ` : ""}
                      {photo.title}
                    </figcaption>
                  </figure>
                );
              })}
            </div>
          ) : (
            <p className="small muted">No photographs in the archive yet.</p>
          )}
        </div>
      </section>

      {save.error && <ErrorNote message={save.error} />}

      {missingImage && (
        <p className="small muted" style={{ marginTop: 10 }}>
          {composer.label} cannot publish a post with no picture, so this will be saved as a
          draft you can finish.
        </p>
      )}

      <div className="row-tight" style={{ marginTop: "var(--space-4)" }}>
        <button
          type="button"
          className="btn btn-primary"
          disabled={!title.trim() || !account || save.running}
          onClick={() => void save.run()}
        >
          {save.running ? "Saving…" : "Save it as a draft"}
        </button>
        <button type="button" className="btn" onClick={() => navigate(-1)}>
          Cancel
        </button>
        <span className="muted small">
          Nothing goes out from here. Saving puts it in front of colleagues to read.
        </span>
      </div>
    </>
  );
}

export default NewPost;
