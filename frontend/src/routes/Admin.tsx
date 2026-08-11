/**
 * Administering the platform: who has an account, and what they can reach.
 *
 * All of this has existed in the API since milestone 1 and had no screen at
 * all, so the only way to add a colleague was a command line — which for an
 * institution means it does not happen, and everybody shares one login. The
 * platform records who changed what, and that record is worth nothing if
 * everybody is the same person.
 *
 * Two decisions worth stating.
 *
 * **Access is shown as a grid, not a form per person.** The question an
 * administrator actually has is "who can see the valuations?", and that is a
 * column, not six separate pages.
 *
 * **A new password is shown once, plainly, and never stored anywhere here.**
 * There is no e-mail on most of these installations, so the realistic way a
 * password reaches somebody is being read out. Pretending otherwise — hiding
 * it behind dots, mailing it into a void — makes the administrator's job
 * impossible rather than secure.
 */

import { useState } from "react";

import { api, type ModuleName, type Page } from "../lib/api";
import { useAction, useQuery, useSession } from "../lib/hooks";
import {
  Badge,
  Empty,
  ErrorNote,
  Loading,
  PageHeader,
  formatDate,
  humanise,
} from "../components/ui";

/**
 * As the list returns them.
 *
 * `/users` is readable by any signed-in account so colleagues can be found, so
 * it deliberately omits contact details — there is no e-mail or sign-in time
 * here, and columns for them would always be blank. The full record is fetched
 * per person when the panel opens, which is also the only place it is needed.
 */
type Person = {
  id: string;
  username: string;
  full_name?: string | null;
  role: string;
  institution?: string | null;
};

type FullPerson = Person & {
  email: string;
  is_active: boolean;
  created_at: string;
  last_login_at?: string | null;
};

type Access = {
  user_id: string;
  username: string;
  is_platform_admin: boolean;
  access: Partial<Record<ModuleName, string>>;
};

const MODULES: ModuleName[] = [
  "archaeology",
  "museum",
  "inventory",
  "management",
  "social_media",
  "activities",
];

const LEVELS = ["", "viewer", "contributor", "editor", "supervisor", "administrator"];
const ROLES = ["visitor", "student", "researcher", "admin"];

export function AdminUsers() {
  const { user, levelIn } = useSession();
  const isAdmin = levelIn("archaeology") === "administrator" && user?.role === "admin";

  const people = useQuery<Page<Person>>(
    (signal) => api.get("/users", { limit: 200 }, signal),
    [],
  );

  if (!isAdmin) {
    return (
      <Empty title="Not your job, happily">
        Managing accounts is the platform administrator's, because it is the one
        thing that can hand somebody the keys to everything else.
      </Empty>
    );
  }

  return (
    <>
      <PageHeader
        title="People"
        subtitle="Who has an account, and what they can reach"
        actions={<NewPerson onCreated={() => people.reload()} />}
      />

      {people.loading ? (
        <Loading />
      ) : people.error ? (
        <ErrorNote message={people.error} onRetry={people.reload} />
      ) : (
        <section className="card">
          <div className="card-body">
            <div className="table-wrap">
              <table className="table table-dense">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Username</th>
                    <th>Role</th>
                    <th>Institution</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {people.data?.items.map((person) => (
                    <PersonRow
                      key={person.id}
                      person={person}
                      onChanged={() => people.reload()}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      )}
    </>
  );
}

function PersonRow({ person, onChanged }: { person: Person; onChanged: () => void }) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <tr>
        <td className="strong">{person.full_name || person.username}</td>
        <td className="mono">{person.username}</td>
        <td>
          <Badge
            value={person.role === "admin" ? "approved" : "draft"}
            kind="review"
            label={humanise(person.role)}
          />
        </td>
        <td className="small muted">{person.institution}</td>
        <td>
          <button type="button" className="btn btn-sm" onClick={() => setOpen((on) => !on)}>
            {open ? "Close" : "Manage"}
          </button>
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={5} style={{ background: "var(--surface-2)" }}>
            <PersonPanel person={person} onChanged={onChanged} />
          </td>
        </tr>
      )}
    </>
  );
}

function PersonPanel({ person, onChanged }: { person: Person; onChanged: () => void }) {
  const full = useQuery<FullPerson>(
    (signal) => api.get(`/users/${person.id}`, undefined, signal),
    [person.id],
  );
  const access = useQuery<Access>(
    (signal) => api.get(`/users/${person.id}/access`, undefined, signal),
    [person.id],
  );

  const setLevel = useAction(async (module: ModuleName, level: string) => {
    if (level) await api.put(`/users/${person.id}/access`, { module, level });
    else await api.delete(`/users/${person.id}/access/${module}`);
    access.reload();
  });

  const setActive = useAction(async (active: boolean) => {
    await api.patch(`/users/${person.id}`, { is_active: active });
    full.reload();
    onChanged();
  });

  const setRole = useAction(async (role: string) => {
    await api.patch(`/users/${person.id}`, { role });
    onChanged();
  });

  return (
    <div style={{ padding: "var(--space-4)" }}>
      {access.error && <ErrorNote message={access.error} />}
      {setLevel.error && <ErrorNote message={setLevel.error} />}
      {setRole.error && <ErrorNote message={setRole.error} />}
      {setActive.error && <ErrorNote message={setActive.error} />}

      <p className="small muted" style={{ marginTop: 0 }}>
        {full.data ? (
          <>
            {full.data.email} · joined {formatDate(full.data.created_at)} ·{" "}
            {full.data.last_login_at
              ? `last signed in ${formatDate(full.data.last_login_at)}`
              : "has never signed in"}
            {full.data.is_active ? "" : " · suspended"}
          </>
        ) : (
          "Loading their details…"
        )}
      </p>

      <div className="row-tight wrap" style={{ marginBottom: "var(--space-4)" }}>
        <label className="row-tight">
          <span className="field-label">Role</span>
          <select
            className="input input-sm select"
            value={person.role}
            onChange={(event) => void setRole.run(event.target.value)}
          >
            {ROLES.map((role) => (
              <option key={role} value={role}>
                {humanise(role)}
              </option>
            ))}
          </select>
        </label>

        <ResetPassword person={person} />

        <button
          type="button"
          className={full.data?.is_active === false ? "btn btn-sm" : "btn btn-sm btn-danger"}
          disabled={setActive.running || !full.data}
          onClick={() => void setActive.run(!full.data?.is_active)}
        >
          {full.data?.is_active === false ? "Let them back in" : "Suspend this account"}
        </button>
      </div>

      {access.data?.is_platform_admin ? (
        <p className="small muted">
          A platform administrator holds every module by definition, so there is
          nothing to grant. Change their role to give them less.
        </p>
      ) : (
        <>
          <p className="small muted">
            What they may do in each part of the platform. Blank means no access
            at all — not even reading.
          </p>
          <div className="table-wrap">
            <table className="table table-dense">
              <thead>
                <tr>
                  {MODULES.map((module) => (
                    <th key={module}>{humanise(module)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  {MODULES.map((module) => (
                    <td key={module}>
                      <select
                        className="input input-sm select"
                        value={access.data?.access[module] ?? ""}
                        disabled={setLevel.running}
                        onChange={(event) => void setLevel.run(module, event.target.value)}
                      >
                        {LEVELS.map((level) => (
                          <option key={level} value={level}>
                            {level ? humanise(level) : "No access"}
                          </option>
                        ))}
                      </select>
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

/**
 * Set somebody a new password and show it once.
 *
 * The alternative on a machine with no outbound mail is an administrator who
 * cannot help a colleague who is locked out, which is the situation this
 * screen exists to end.
 */
function ResetPassword({ person }: { person: Person }) {
  const [shown, setShown] = useState<string | null>(null);
  const [value, setValue] = useState("");
  const [asking, setAsking] = useState(false);

  const reset = useAction(async () => {
    const password = value.trim();
    await api.post(`/users/${person.id}/reset-password`, { new_password: password });
    setShown(password);
    setValue("");
    setAsking(false);
  });

  return (
    <>
      <button type="button" className="btn btn-sm" onClick={() => setAsking(true)}>
        Set a new password
      </button>

      {asking && (
        <div className="modal-scrim" role="dialog" aria-modal="true">
          <div className="modal">
            <h2 className="modal-title">New password for {person.username}</h2>
            <p className="small muted">
              Ten characters or more, with an upper case letter, a lower case
              letter and a digit. They can change it once they are in.
            </p>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void reset.run();
              }}
            >
              {reset.error && <ErrorNote message={reset.error} />}
              <div className="field">
                <label className="field-label" htmlFor={`pw-${person.id}`}>
                  Password
                </label>
                <input
                  id={`pw-${person.id}`}
                  className="input mono"
                  required
                  minLength={10}
                  value={value}
                  onChange={(event) => setValue(event.target.value)}
                />
              </div>
              <div className="row-tight">
                <button type="button" className="btn" onClick={() => setAsking(false)}>
                  Cancel
                </button>
                <button className="btn btn-primary" type="submit" disabled={reset.running}>
                  {reset.running ? "Setting…" : "Set it"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {shown && (
        <div className="modal-scrim" role="dialog" aria-modal="true">
          <div className="modal">
            <h2 className="modal-title">Done</h2>
            <p>
              {person.username} can now sign in with:
            </p>
            <p className="mono strong" style={{ fontSize: "var(--text-body)" }}>
              {shown}
            </p>
            <p className="small muted">
              This is the only time it is shown. Nothing here stores it — it is
              hashed the moment it reaches the server. Tell them in person or by
              a message you trust, and ask them to change it.
            </p>
            <div className="row-tight">
              <button type="button" className="btn" onClick={() => setShown(null)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function NewPerson({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    full_name: "",
    username: "",
    email: "",
    password: "",
    role: "student",
  });
  const [tellThem, setTellThem] = useState(true);
  // What happened to the welcome message, kept after the form closes: an
  // administrator who believes somebody was told their password will not tell
  // them, so "the account was made but the e-mail did not go" has to survive
  // on screen rather than flash past.
  const [outcome, setOutcome] = useState<{ sent: boolean; note: string } | null>(null);

  const create = useAction(async () => {
    const result = await api.post<{ welcome_email_sent: boolean; welcome_email_note: string }>(
      "/users",
      {
        full_name: form.full_name || null,
        username: form.username.trim(),
        email: form.email.trim(),
        password: form.password,
        role: form.role,
        send_welcome_email: tellThem,
      },
    );
    setOpen(false);
    setForm({ full_name: "", username: "", email: "", password: "", role: "student" });
    setOutcome({ sent: result.welcome_email_sent, note: result.welcome_email_note });
    onCreated();
  });

  return (
    <>
      <button type="button" className="btn btn-primary" onClick={() => setOpen(true)}>
        Add a person
      </button>

      {outcome && (
        <div
          className={`alert ${outcome.sent ? "alert-info" : "alert-warning"}`}
          style={{ marginTop: 10 }}
        >
          <b>Account created.</b> {outcome.note}
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            style={{ marginLeft: 8 }}
            onClick={() => setOutcome(null)}
          >
            Dismiss
          </button>
        </div>
      )}

      {open && (
        <div className="modal-scrim" role="dialog" aria-modal="true">
          <div className="modal">
            <h2 className="modal-title">Add a person</h2>
            <p className="small muted">
              Give everybody their own account rather than sharing one. The
              platform records who changed what, and that is worth nothing if
              everybody is you.
            </p>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void create.run();
              }}
            >
              {create.error && <ErrorNote message={create.error} />}

              <div className="field">
                <label className="field-label" htmlFor="np-name">
                  Name
                </label>
                <input
                  id="np-name"
                  className="input"
                  value={form.full_name}
                  onChange={(event) => setForm({ ...form, full_name: event.target.value })}
                />
              </div>
              <div className="field">
                <label className="field-label" htmlFor="np-user">
                  Username
                </label>
                <input
                  id="np-user"
                  className="input mono"
                  required
                  value={form.username}
                  onChange={(event) => setForm({ ...form, username: event.target.value })}
                />
              </div>
              <div className="field">
                <label className="field-label" htmlFor="np-email">
                  E-mail
                </label>
                <input
                  id="np-email"
                  className="input"
                  type="email"
                  required
                  value={form.email}
                  onChange={(event) => setForm({ ...form, email: event.target.value })}
                />
              </div>
              <div className="field">
                <label className="field-label" htmlFor="np-pw">
                  First password
                </label>
                <input
                  id="np-pw"
                  className="input mono"
                  required
                  minLength={10}
                  value={form.password}
                  onChange={(event) => setForm({ ...form, password: event.target.value })}
                />
                <p className="field-help">
                  Ten characters or more, with an upper case letter, a lower case
                  letter and a digit. Tell it to them and ask them to change it.
                </p>
              </div>
              <div className="field">
                <label className="field-label" htmlFor="np-role">
                  Role
                </label>
                <select
                  id="np-role"
                  className="input select"
                  value={form.role}
                  onChange={(event) => setForm({ ...form, role: event.target.value })}
                >
                  {ROLES.map((role) => (
                    <option key={role} value={role}>
                      {humanise(role)}
                    </option>
                  ))}
                </select>
                <p className="field-help">
                  This decides what they can do in archaeology and whether they
                  administer the platform. Everything else is granted per module
                  afterwards.
                </p>
              </div>

              <div className="field">
                <label className="chip-check">
                  <input
                    type="checkbox"
                    checked={tellThem}
                    onChange={(event) => setTellThem(event.target.checked)}
                  />
                  E-mail them their sign-in details
                </label>
                <p className="field-help">
                  Sends the address, their username and this password. The password
                  travels through e-mail in the clear, so the message tells them to
                  change it as soon as they are in. Turn this off to hand it over
                  yourself.
                </p>
              </div>

              <div className="row-tight">
                <button type="button" className="btn" onClick={() => setOpen(false)}>
                  Cancel
                </button>
                <button className="btn btn-primary" type="submit" disabled={create.running}>
                  {create.running ? "Creating…" : "Create the account"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
