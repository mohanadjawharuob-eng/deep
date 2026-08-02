/**
 * Whose installation this is — and, separately, who you are.
 *
 * Two screens in one file because they are the same job at two scales: an
 * image is uploaded, decoded by the API, and then appears on every page.
 *
 * The branding half is deliberately small. An installation does not need a
 * theme editor; it needs its own name and its own mark, so that a department
 * that has put twenty years of records into this thing is not looking at
 * somebody else's product name all day. Everything past that — colours, fonts —
 * is a way to make the platform look worse, and is left out.
 */

import { useRef, useState } from "react";

import { api } from "../lib/api";
import { useAction, useBranding, useSession } from "../lib/hooks";
import { Avatar, ErrorNote, PageHeader } from "../components/ui";

/* ==========================================================================
 * The institution
 * ======================================================================= */
export function Appearance() {
  const { user } = useSession();
  const { branding, refresh } = useBranding();

  const [name, setName] = useState<string | null>(null);
  const [tagline, setTagline] = useState<string | null>(null);
  const [footer, setFooter] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  // Null means "not edited on this screen", which is how the form starts
  // showing what is stored without a `useEffect` that fights the user's typing
  // every time the branding refreshes.
  const nameValue = name ?? branding.organisation_name ?? "";
  const taglineValue = tagline ?? branding.tagline ?? "";
  const footerValue = footer ?? branding.footer_note ?? "";

  const save = useAction(async () => {
    await api.put("/branding", {
      organisation_name: nameValue,
      tagline: taglineValue,
      footer_note: footerValue,
    });
    await refresh();
    setSaved(true);
  });

  if (user?.role !== "admin") {
    return (
      <>
        <PageHeader title="Appearance" />
        <div className="card">
          <div className="card-body muted">
            The name and mark at the top of every page are set by the platform
            administrator. Your own photograph is under <b>My profile</b>.
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Appearance"
        subtitle="The name and mark everybody sees, on every page and on the sign-in screen."
      />

      <div className="card" style={{ maxWidth: 720 }}>
        <div className="card-body">
          <div className="overline" style={{ marginBottom: 12 }}>
            Logo
          </div>
          <LogoUpload />
        </div>
      </div>

      <div className="card" style={{ maxWidth: 720, marginTop: 16 }}>
        <div className="card-body">
          <div className="overline" style={{ marginBottom: 12 }}>
            Name
          </div>

          <label className="field">
            <span className="field-label">Organisation</span>
            <input
              className="input"
              value={nameValue}
              maxLength={120}
              placeholder="Stratum"
              onChange={(event) => {
                setName(event.target.value);
                setSaved(false);
              }}
            />
            <span className="field-help">
              Replaces “Stratum” in the sidebar, on the sign-in page and in the
              browser tab. Leave it empty to keep the platform's own name.
            </span>
          </label>

          <label className="field">
            <span className="field-label">Tagline</span>
            <input
              className="input"
              value={taglineValue}
              maxLength={160}
              placeholder="Department of Antiquities"
              onChange={(event) => {
                setTagline(event.target.value);
                setSaved(false);
              }}
            />
          </label>

          <label className="field">
            <span className="field-label">Note at the foot of exported files</span>
            <textarea
              className="input"
              rows={3}
              value={footerValue}
              maxLength={2000}
              placeholder="© 2026 Department of Antiquities. Not for redistribution."
              onChange={(event) => {
                setFooter(event.target.value);
                setSaved(false);
              }}
            />
            <span className="field-help">
              Printed on exported workbooks and reports, not on screen. The place
              a rights statement matters is the file that leaves the building.
            </span>
          </label>

          {save.error && <ErrorNote message={save.error} />}

          <div className="row-tight" style={{ marginTop: 12 }}>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void save.run()}
              disabled={save.running}
            >
              {save.running ? "Saving…" : "Save"}
            </button>
            {saved && !save.running && <span className="muted small">Saved.</span>}
          </div>
        </div>
      </div>
    </>
  );
}

function LogoUpload() {
  const { branding, refresh } = useBranding();
  const input = useRef<HTMLInputElement>(null);

  const upload = useAction(async (file: File) => {
    await api.upload("/branding/logo", file);
    await refresh();
  });
  const remove = useAction(async () => {
    await api.delete("/branding/logo");
    await refresh();
  });

  return (
    <>
      <div className="row-tight" style={{ alignItems: "center", gap: 16 }}>
        <span className="logo-preview">
          {branding.logo_url ? (
            <img src={branding.logo_url} alt="The current logo" />
          ) : (
            <span className="muted small">None</span>
          )}
        </span>

        <div>
          <input
            ref={input}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            style={{ display: "none" }}
            onChange={(event) => {
              const file = event.target.files?.[0];
              // Cleared so choosing the same file twice fires the change event
              // the second time — which is what somebody does after a failure.
              event.target.value = "";
              if (file) void upload.run(file);
            }}
          />
          <div className="row-tight">
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => input.current?.click()}
              disabled={upload.running}
            >
              {upload.running ? "Uploading…" : branding.logo_url ? "Replace…" : "Upload…"}
            </button>
            {branding.logo_url && (
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => void remove.run()}
                disabled={remove.running}
              >
                Remove
              </button>
            )}
          </div>
          <p className="muted small" style={{ marginTop: 8, marginBottom: 0 }}>
            PNG, JPEG, WebP or GIF. It is drawn about 28 pixels high, so around
            240 pixels on the long edge is plenty. Not SVG — an SVG can carry
            script, and this one is served to everybody including people who are
            not signed in.
          </p>
        </div>
      </div>

      {upload.error && <ErrorNote message={upload.error} />}
      {remove.error && <ErrorNote message={remove.error} />}
    </>
  );
}

/* ==========================================================================
 * The person
 * ======================================================================= */
export function MyProfile() {
  const { user, reload } = useSession();
  const [version, setVersion] = useState(0);

  const input = useRef<HTMLInputElement>(null);
  // What the API last told us: it is the truth about whether a photograph
  // exists, and `user` in the session was fetched before any of this happened.
  const [hasPhoto, setHasPhoto] = useState<boolean | null>(null);

  const upload = useAction(async (file: File) => {
    await api.upload("/users/me/avatar", file);
    setHasPhoto(true);
    // The sidebar draws from the session's copy of the account, which was
    // fetched before any of this. Without this it keeps showing initials until
    // the next sign-in.
    await reload();
    // The path in the store changes but the URL does not, so remounting the
    // avatar is what makes the new photograph appear rather than the old one.
    setVersion((current) => current + 1);
  });

  const remove = useAction(async () => {
    await api.delete("/users/me/avatar");
    setHasPhoto(false);
    await reload();
    setVersion((current) => current + 1);
  });

  const showing = hasPhoto ?? user?.has_avatar ?? false;

  return (
    <>
      <PageHeader
        title="My profile"
        subtitle="Your photograph, shown beside your name and against what you record."
      />

      <div className="card" style={{ maxWidth: 720 }}>
        <div className="card-body">
          <div className="row-tight" style={{ alignItems: "center", gap: 16 }}>
            <Avatar
              key={version}
              userId={user?.id}
              name={user?.full_name ?? user?.username}
              hasPhoto={showing}
              size={72}
            />

            <div>
              <input
                ref={input}
                type="file"
                accept="image/png,image/jpeg,image/webp,image/gif"
                style={{ display: "none" }}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  event.target.value = "";
                  if (file) void upload.run(file);
                }}
              />
              <div className="row-tight">
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => input.current?.click()}
                  disabled={upload.running}
                >
                  {upload.running ? "Uploading…" : "Choose a photograph…"}
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => void remove.run()}
                  disabled={remove.running || !showing}
                >
                  Remove
                </button>
              </div>
              <p className="muted small" style={{ marginTop: 8, marginBottom: 0 }}>
                It is stored at 256 pixels square — anything larger is downloaded
                on every page for no visible difference. Only people with an
                account can see it.
              </p>
            </div>
          </div>

          {upload.error && <ErrorNote message={upload.error} />}
          {remove.error && <ErrorNote message={remove.error} />}
        </div>
      </div>

      <div className="card" style={{ maxWidth: 720, marginTop: 16 }}>
        <div className="card-body">
          <div className="overline" style={{ marginBottom: 12 }}>
            Account
          </div>
          <dl className="detail-grid">
            <div>
              <dt>Name</dt>
              <dd>{user?.full_name}</dd>
            </div>
            <div>
              <dt>Username</dt>
              <dd className="mono">{user?.username}</dd>
            </div>
            <div>
              <dt>E-mail</dt>
              <dd>{user?.email}</dd>
            </div>
            <div>
              <dt>Role</dt>
              <dd>{user?.role}</dd>
            </div>
          </dl>
          <p className="muted small" style={{ marginBottom: 0 }}>
            Your name, e-mail and password are changed by the platform
            administrator.
          </p>
        </div>
      </div>
    </>
  );
}
