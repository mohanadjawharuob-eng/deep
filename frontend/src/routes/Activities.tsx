/**
 * The activity hub: what we did, what it took, and what it cost.
 *
 * Three things here are decisions rather than layout.
 *
 * **The countdown comes first.** An activity opens with what is still
 * outstanding and how late it is getting, above the description of what
 * happened. Somebody opening a past season is usually about to repeat it, and
 * the useful thing is not the prose — it is "the licence took 46 days last
 * time and you have ten".
 *
 * **Costs are drawn per currency, and estimates are marked.** There is no
 * single total anywhere on this screen. A figure that mixes a dinar with a
 * dollar, or a quotation with an invoice, is a figure somebody eventually has
 * to explain to a funder.
 *
 * **Anything provisional is drawn with a broken line**, as everywhere else in
 * this platform: an estimated cost, an ungranted permit, an unticked
 * preparation. The reader sees what is settled without reading a word, and it
 * is never colour alone — each carries a word as well.
 */

import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  api,
  type ActivityPermit,
  type HubActivity,
  type HubActivityDetail,
  type BriefResult,
  type HubSummary,
  type Page,
} from "../lib/api";
import { useAction, useDebounced, useQuery } from "../lib/hooks";
import {
  Badge,
  DeleteRecord,
  Detail,
  DetailGrid,
  Empty,
  ErrorNote,
  Loading,
  PageHeader,
  Pager,
  SearchInput,
  formatDate,
  humanise,
} from "../components/ui";

const PAGE = 50;

const KINDS = [
  "excavation",
  "survey",
  "fieldwalking",
  "geophysics",
  "underwater",
  "recording",
  "conservation",
  "laboratory",
  "training",
  "outreach",
  "exhibition",
  "conference",
  "site_visit",
  "maintenance",
  "other",
];

const STATUSES = ["planned", "approved", "in_progress", "completed", "postponed", "cancelled"];

/** Money: two decimals and a code. Never converted, never combined. */
function money(value: number, currency: string) {
  return `${Number(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} ${currency}`;
}

/** A quantity without the trailing zeros a fixed-scale decimal drags along. */
function tidy(value: number) {
  return Number(value).toString();
}

function when(activity: HubActivity) {
  if (activity.starts_on && activity.ends_on && activity.starts_on !== activity.ends_on) {
    return `${formatDate(activity.starts_on)} – ${formatDate(activity.ends_on)}`;
  }
  return formatDate(activity.starts_on) ?? formatDate(activity.ends_on) ?? "No dates yet";
}

/* ==========================================================================
 * The hub's front page
 * ======================================================================= */
export function ActivityHub() {
  const summary = useQuery<HubSummary>(
    (signal) => api.get("/activities/summary", undefined, signal),
    [],
  );

  return (
    <>
      <PageHeader
        title="Activity hub"
        subtitle="What we have done, and what it took"
        actions={
          <>
            <Link className="btn" to="/activities/all">
              All activities
            </Link>
            <Link className="btn btn-primary" to="/activities/new">
              Record an activity
            </Link>
          </>
        }
      />

      {summary.loading ? (
        <Loading />
      ) : summary.error ? (
        <ErrorNote message={summary.error} onRetry={summary.reload} />
      ) : !summary.data || summary.data.total === 0 ? (
        <Empty title="Nothing recorded yet">
          An activity is anything the institution did — a season, a survey, a school visit, a week
          in the store. Record one and everything it took comes with it: the kit, the permissions,
          what had to be arranged beforehand, and what it cost.
        </Empty>
      ) : (
        <>
          {summary.data.needing_attention.length > 0 && (
            <div className="alert alert-warning" style={{ marginBottom: "var(--space-5)" }}>
              <div>
                <div className="strong">Still to do</div>
                <div className="small">
                  These have not happened yet and have permissions or preparations outstanding.
                </div>
                <AgendaList items={summary.data.needing_attention} />
              </div>
            </div>
          )}

          {summary.data.expiring_permits.length > 0 && (
            <div className="alert alert-warning" style={{ marginBottom: "var(--space-5)" }}>
              <div>
                <div className="strong">Permissions running out within a month</div>
                <ul className="small" style={{ margin: "var(--space-2) 0 0", paddingLeft: "1.2em" }}>
                  {summary.data.expiring_permits.map((permit) => (
                    <li key={permit.id}>
                      <span className="strong">{permit.name}</span>
                      {permit.issuer ? ` · ${permit.issuer}` : ""} — expires{" "}
                      {formatDate(permit.expires_on)}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          <div className="pair">
            <section className="card">
              <div className="card-header">
                <h2 className="card-title">Coming up</h2>
              </div>
              <div className="card-body">
                {summary.data.upcoming.length === 0 ? (
                  <p className="small muted">Nothing in the diary.</p>
                ) : (
                  <AgendaList items={summary.data.upcoming} />
                )}
              </div>
            </section>

            <section className="card">
              <div className="card-header">
                <h2 className="card-title">Recently</h2>
              </div>
              <div className="card-body">
                {summary.data.recent.length === 0 ? (
                  <p className="small muted">Nothing recorded yet.</p>
                ) : (
                  <AgendaList items={summary.data.recent} />
                )}
              </div>
            </section>
          </div>

          <section className="card" style={{ marginTop: "var(--space-5)" }}>
            <div className="card-header">
              <h2 className="card-title">What we do</h2>
            </div>
            <div className="card-body">
              <div className="chips">
                {Object.entries(summary.data.by_kind)
                  .sort((a, b) => b[1] - a[1])
                  .map(([kind, count]) => (
                    <Link key={kind} className="chip" to={`/activities/all?kind=${kind}`}>
                      {humanise(kind)} <span className="muted">{count}</span>
                    </Link>
                  ))}
              </div>
            </div>
          </section>
        </>
      )}
    </>
  );
}

function AgendaList({ items }: { items: HubActivity[] }) {
  return (
    <ul className="agenda">
      {items.map((activity) => (
        <li key={activity.id}>
          <div className="agenda-when">
            <span className="strong">{when(activity)}</span>
            {activity.duration_days ? (
              <span className="small muted">{activity.duration_days} days</span>
            ) : null}
          </div>
          <div className="agenda-what">
            <Link className="strong" to={`/activities/${activity.id}`}>
              {activity.title}
            </Link>
            <span className="small muted">
              {[humanise(activity.kind), activity.location, activity.lead_label]
                .filter(Boolean)
                .join(" · ")}
            </span>
            {/* Inside the second column rather than beside it: `.agenda li` is
                a two-column grid, and a third child wraps onto its own row. */}
            {activity.outstanding_count > 0 && (
              <span>
                <Badge
                  value="pending"
                  kind="review"
                  label={`${activity.outstanding_count} still to do`}
                />
              </span>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

/* ==========================================================================
 * Searching
 * ======================================================================= */
export function Activities() {
  const [params, setParams] = useSearchParams();
  const [term, setTerm] = useState(params.get("q") ?? "");
  const debounced = useDebounced(term);
  const offset = Number(params.get("offset") ?? 0);
  const kind = params.get("kind") ?? "";
  const status = params.get("status") ?? "";

  const activities = useQuery<Page<HubActivity>>(
    (signal) =>
      api.get(
        "/activities",
        {
          q: debounced || undefined,
          kind: kind || undefined,
          status: status || undefined,
          limit: PAGE,
          offset,
        },
        signal,
      ),
    [debounced, kind, status, offset],
  );

  function setFilter(name: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    next.delete("offset");
    setParams(next);
  }

  return (
    <>
      <PageHeader
        title="Activities"
        subtitle={
          activities.data
            ? `${activities.data.total} recorded`
            : "Everything the institution has done"
        }
        actions={
          <Link className="btn btn-primary" to="/activities/new">
            Record an activity
          </Link>
        }
      />

      <div className="toolbar">
        <SearchInput value={term} onChange={setTerm} placeholder="Title, place, outcome…" />
        <select
          className="input input-sm filter-select"
          value={kind}
          onChange={(event) => setFilter("kind", event.target.value)}
        >
          <option value="">Any kind</option>
          {KINDS.map((value) => (
            <option key={value} value={value}>
              {humanise(value)}
            </option>
          ))}
        </select>
        <select
          className="input input-sm filter-select"
          value={status}
          onChange={(event) => setFilter("status", event.target.value)}
        >
          <option value="">Any status</option>
          {STATUSES.map((value) => (
            <option key={value} value={value}>
              {humanise(value)}
            </option>
          ))}
        </select>
      </div>

      {activities.loading ? (
        <Loading />
      ) : activities.error ? (
        <ErrorNote message={activities.error} onRetry={activities.reload} />
      ) : activities.data && activities.data.items.length === 0 ? (
        <Empty title="Nothing matches">Try a different word, or clear the filters.</Empty>
      ) : (
        <>
          <section className="card">
            <div className="card-body">
              <AgendaList items={activities.data?.items ?? []} />
            </div>
          </section>
          {activities.data && (
            <Pager
              total={activities.data.total}
              limit={PAGE}
              offset={offset}
              onChange={(next) => {
                const updated = new URLSearchParams(params);
                updated.set("offset", String(next));
                setParams(updated);
              }}
            />
          )}
        </>
      )}
    </>
  );
}

/* ==========================================================================
 * Recording one
 * ======================================================================= */
export function NewActivity() {
  const navigate = useNavigate();
  const [form, setForm] = useState({
    title: "",
    kind: "excavation",
    starts_on: "",
    ends_on: "",
    location: "",
    summary: "",
  });

  const create = useAction(async () => {
    const body = await api.post<HubActivityDetail>("/activities", {
      title: form.title,
      kind: form.kind,
      starts_on: form.starts_on || null,
      ends_on: form.ends_on || null,
      location: form.location || null,
      summary: form.summary || null,
    });
    navigate(`/activities/${body.id}`);
  });

  return (
    <>
      <PageHeader
        title="Record an activity"
        subtitle="A season, a survey, a visit, a week's work"
      />

      <form
        className="card"
        onSubmit={(event) => {
          event.preventDefault();
          void create.run();
        }}
      >
        <div className="card-body">
          {create.error && <ErrorNote message={create.error} />}

          <div className="field">
            <label className="field-label" htmlFor="activity-title">
              What was it?
            </label>
            <input
              id="activity-title"
              className="input"
              required
              value={form.title}
              onChange={(event) => setForm({ ...form, title: event.target.value })}
              placeholder="North trench, 2019"
            />
          </div>

          <div className="field">
            <label className="field-label" htmlFor="activity-kind">
              Kind
            </label>
            <select
              id="activity-kind"
              className="input select"
              value={form.kind}
              onChange={(event) => setForm({ ...form, kind: event.target.value })}
            >
              {KINDS.map((value) => (
                <option key={value} value={value}>
                  {humanise(value)}
                </option>
              ))}
            </select>
          </div>

          <div className="row">
            <div className="field col">
              <label className="field-label" htmlFor="activity-from">
                From
              </label>
              <input
                id="activity-from"
                className="input"
                type="date"
                value={form.starts_on}
                onChange={(event) => setForm({ ...form, starts_on: event.target.value })}
              />
            </div>
            <div className="field col">
              <label className="field-label" htmlFor="activity-to">
                To
              </label>
              <input
                id="activity-to"
                className="input"
                type="date"
                value={form.ends_on}
                onChange={(event) => setForm({ ...form, ends_on: event.target.value })}
              />
            </div>
          </div>
          <p className="field-help">
            Leave the dates out if it has not been arranged yet. Writing it down now is the point.
          </p>

          <div className="field">
            <label className="field-label" htmlFor="activity-where">
              Where
            </label>
            <input
              id="activity-where"
              className="input"
              value={form.location}
              onChange={(event) => setForm({ ...form, location: event.target.value })}
              placeholder="Wadi Rum — or the store room"
            />
          </div>

          <div className="field">
            <label className="field-label" htmlFor="activity-summary">
              What happened
            </label>
            <textarea
              id="activity-summary"
              className="input textarea"
              rows={4}
              value={form.summary}
              onChange={(event) => setForm({ ...form, summary: event.target.value })}
            />
          </div>

          <div className="row-tight">
            <button className="btn btn-primary" type="submit" disabled={create.running}>
              {create.running ? "Saving…" : "Record it"}
            </button>
          </div>
        </div>
      </form>
    </>
  );
}

/* ==========================================================================
 * One activity, with everything on it
 * ======================================================================= */
export function ActivityScreen() {
  const { activityId } = useParams();
  const navigate = useNavigate();
  const activity = useQuery<HubActivityDetail>(
    (signal) => api.get(`/activities/${activityId}`, undefined, signal),
    [activityId],
  );

  if (activity.loading) return <Loading />;
  if (activity.error) return <ErrorNote message={activity.error} onRetry={activity.reload} />;
  if (!activity.data) return null;

  const record = activity.data;

  return (
    <>
      <PageHeader
        title={record.title}
        subtitle={[humanise(record.kind), when(record), record.location]
          .filter(Boolean)
          .join(" · ")}
        actions={
          <>
            <BriefButtons activity={record} />
            {record.can_edit && <RepeatButton activity={record} />}
            <DeleteRecord
              name={record.title}
              title="Delete this activity?"
              takesWithIt="its kit list, permits, preparations and costings"
              can={record.can_delete}
              onDelete={() => api.delete(`/activities/${record.id}`)}
              onDeleted={() => navigate("/activities")}
            />
          </>
        }
      />

      {/* First on the page, because somebody opening a past season is usually
          about to repeat it, and this is what they came for. */}
      <Outstanding activity={record} />

      <DetailGrid>
        <Detail label="Status" value={<Badge value={record.status} kind="status" />} />
        <Detail label="Led by" value={record.lead_label} />
        <Detail label="Team" value={record.team_size ? `${record.team_size} people` : null} />
        <Detail
          label="Project"
          value={
            record.project_name && record.project_id ? (
              <Link to={`/projects/${record.project_id}`}>{record.project_name}</Link>
            ) : null
          }
        />
        <Detail
          label="Site"
          value={
            record.site_name && record.site_id ? (
              <Link to={`/sites/${record.site_id}`}>{record.site_name}</Link>
            ) : null
          }
        />
        <Detail
          label="Repeated from"
          value={
            record.repeated_from_id ? (
              <Link to={`/activities/${record.repeated_from_id}`}>
                {record.repeated_from_title}
              </Link>
            ) : null
          }
        />
      </DetailGrid>

      {record.repeat_count > 0 && (
        <p className="small muted">
          Run again {record.repeat_count} {record.repeat_count === 1 ? "time" : "times"} since.
        </p>
      )}

      {record.summary && (
        <section className="card">
          <div className="card-header">
            <h2 className="card-title">What it was</h2>
          </div>
          <div className="card-body">
            <p className="prose">{record.summary}</p>
          </div>
        </section>
      )}

      <Costs activity={record} />
      <Permits permits={record.permits} />
      <Preparations activity={record} onChanged={activity.reload} />
      <Kit activity={record} />
      <Photos activity={record} />

      {record.outcome && (
        <section className="card">
          <div className="card-header">
            <h2 className="card-title">Outcome</h2>
          </div>
          <div className="card-body">
            <p className="prose">{record.outcome}</p>
          </div>
        </section>
      )}

      {record.lessons && (
        <section className="card">
          <div className="card-header">
            <h2 className="card-title">What to do differently</h2>
          </div>
          <div className="card-body">
            <p className="prose">{record.lessons}</p>
          </div>
        </section>
      )}
    </>
  );
}

function Outstanding({ activity }: { activity: HubActivityDetail }) {
  const { outstanding } = activity;
  if (outstanding.is_clear) return null;

  const urgent = outstanding.too_late.length > 0;
  // A finished season's unticked boxes are history, not a to-do list. Drawn as
  // a note rather than a warning, and titled differently: telling a 2019
  // excavation it is running out of time is how people learn to ignore the
  // colour altogether.
  const tone = !outstanding.is_actionable ? "alert-info" : urgent ? "alert-danger" : "alert-warning";

  return (
    <div className={`alert ${tone}`} style={{ marginBottom: "var(--space-5)" }}>
      <div>
        <div className="strong">
          {outstanding.is_actionable ? "Still outstanding" : "Never done"}
        </div>

        {urgent && (
          <>
            <p className="small strong" style={{ margin: "var(--space-2) 0 0" }}>
              Not enough time left, going by how long these have taken before:
            </p>
            <ul className="small" style={{ margin: "2px 0 0", paddingLeft: "1.2em" }}>
              {outstanding.too_late.map((entry) => (
                <li key={entry} className="strong">
                  {entry}
                </li>
              ))}
            </ul>
          </>
        )}

        {outstanding.permits.length > 0 && (
          <>
            <p className="small strong" style={{ margin: "var(--space-3) 0 0" }}>
              Permissions
            </p>
            <ul className="small" style={{ margin: "2px 0 0", paddingLeft: "1.2em" }}>
              {outstanding.permits.map((entry) => (
                <li key={entry}>{entry}</li>
              ))}
            </ul>
          </>
        )}

        {outstanding.preparations.length > 0 && (
          <>
            <p className="small strong" style={{ margin: "var(--space-3) 0 0" }}>
              Preparations
            </p>
            <ul className="small" style={{ margin: "2px 0 0", paddingLeft: "1.2em" }}>
              {outstanding.preparations.map((entry) => (
                <li key={entry}>{entry}</li>
              ))}
            </ul>
          </>
        )}

        {outstanding.is_actionable && outstanding.longest_lead_days != null && (
          <p className="small muted" style={{ marginTop: "var(--space-3)" }}>
            The longest of these has taken {outstanding.longest_lead_days} days before. That is how
            far ahead of the start date it should already be under way.
          </p>
        )}
      </div>
    </div>
  );
}

function Costs({ activity }: { activity: HubActivityDetail }) {
  const { cost_summary: summary, costs } = activity;
  if (costs.length === 0 && summary.by_currency.length === 0) return null;

  return (
    <section className="card">
      <div className="card-header">
        <h2 className="card-title">Costs</h2>
      </div>
      <div className="card-body">
        <div className="stat-grid">
          {summary.by_currency.map((line) => (
            <div className="stat" key={line.currency}>
              <span className="stat-label">{line.currency}</span>
              <span className="stat-value">{money(line.amount, line.currency)}</span>
              {line.estimated_amount > 0 && (
                <span className="stat-note">
                  of which {money(line.estimated_amount, line.currency)} estimated
                </span>
              )}
            </div>
          ))}
        </div>

        {summary.by_currency.length > 1 && (
          <p className="small muted" style={{ marginTop: "var(--space-3)" }}>
            Kept apart on purpose. Adding one currency to another gives a number that is wrong in a
            way nobody notices until a funder does.
          </p>
        )}

        {costs.length > 0 && (
          <div className="table-wrap" style={{ marginTop: "var(--space-4)" }}>
            <table className="table table-dense">
              <thead>
                <tr>
                  <th>What</th>
                  <th>Each</th>
                  <th className="numeric">Total</th>
                  <th>Supplier</th>
                </tr>
              </thead>
              <tbody>
                {costs.map((line) => (
                  <tr key={line.id} className={line.is_estimate ? "provisional" : undefined}>
                    <td>
                      {line.description}{" "}
                      {line.is_estimate && (
                        <Badge value="draft" kind="review" label="estimate" />
                      )}
                    </td>
                    <td className="small muted">
                      {money(line.unit_cost, line.currency)}
                      {line.unit ? `/${line.unit}` : ""} × {tidy(line.quantity)}
                    </td>
                    <td className="numeric">{money(line.total, line.currency)}</td>
                    <td className="small muted">{line.supplier}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}

/** Granted and not-required read as settled; everything else is provisional. */
function permitTone(permit: ActivityPermit) {
  if (permit.status === "granted" || permit.status === "not_required") return "approved";
  if (permit.status === "refused") return "rejected";
  return "pending";
}

function Permits({ permits }: { permits: ActivityPermit[] }) {
  if (permits.length === 0) return null;

  return (
    <section className="card">
      <div className="card-header">
        <h2 className="card-title">Permissions and paperwork</h2>
      </div>
      <div className="card-body">
        <ul className="checklist">
          {permits.map((permit) => (
            <li
              key={permit.id}
              className={permit.status === "granted" ? undefined : "provisional"}
            >
              <div className="row-tight wrap">
                <span className="strong">{permit.name}</span>
                <Badge value={permitTone(permit)} kind="review" label={humanise(permit.status)} />
                {permit.issuer && <span className="small muted">{permit.issuer}</span>}
                {permit.reference && <span className="small mono">{permit.reference}</span>}
              </div>
              <div className="small muted">
                {permit.days_to_obtain != null ? (
                  <>Took {permit.days_to_obtain} days to get. </>
                ) : permit.lead_time_days != null ? (
                  <>Allow {permit.lead_time_days} days. </>
                ) : null}
                {permit.expires_on && <>Expires {formatDate(permit.expires_on)}. </>}
                {permit.cost != null && permit.cost > 0 && (
                  <>Fee {money(permit.cost, permit.currency ?? "USD")}. </>
                )}
                {permit.contact && <>Contact: {permit.contact}.</>}
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function Preparations({
  activity,
  onChanged,
}: {
  activity: HubActivityDetail;
  onChanged: () => void;
}) {
  const tick = useAction(async (id: string, done: boolean) => {
    await api.patch(`/activities/${activity.id}/preparations/${id}`, { is_done: done });
    onChanged();
  });

  if (activity.preparations.length === 0) return null;

  return (
    <section className="card">
      <div className="card-header">
        <h2 className="card-title">Preparations</h2>
      </div>
      <div className="card-body">
        {tick.error && <ErrorNote message={tick.error} />}
        <ul className="checklist">
          {activity.preparations.map((step) => (
            <li key={step.id} className={step.is_done ? undefined : "provisional"}>
              <label className="row-tight">
                <input
                  className="checkbox"
                  type="checkbox"
                  checked={step.is_done}
                  disabled={!activity.can_edit || tick.running}
                  onChange={(event) => void tick.run(step.id, event.target.checked)}
                />
                <span className={step.is_done ? "muted" : "strong"}>{step.description}</span>
              </label>
              <div className="small muted">
                {step.lead_time_days != null && <>{step.lead_time_days} days ahead</>}
                {step.due_on && <> · by {formatDate(step.due_on)}</>}
                {step.responsible_label && <> · {step.responsible_label}</>}
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function Kit({ activity }: { activity: HubActivityDetail }) {
  if (activity.equipment.length === 0) return null;

  return (
    <section className="card">
      <div className="card-header">
        <h2 className="card-title">Equipment</h2>
      </div>
      <div className="card-body">
        <ul className="checklist">
          {activity.equipment.map((item) => (
            <li key={item.id}>
              <div className="row-tight wrap">
                <span className="strong">
                  {tidy(item.quantity)}
                  {item.unit ? ` ${item.unit}` : ""} × {item.label}
                </span>
                {item.equipment_id && item.equipment_exists && (
                  <Link className="small" to={`/inventory/equipment/${item.equipment_id}`}>
                    {item.asset_number ?? "in the inventory"}
                  </Link>
                )}
                {item.source && <span className="small muted">{item.source}</span>}
              </div>
              {item.performance_notes && (
                <div className="small muted">{item.performance_notes}</div>
              )}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function Photos({ activity }: { activity: HubActivityDetail }) {
  if (activity.photos.length === 0) return null;

  return (
    <section className="card">
      <div className="card-header">
        <h2 className="card-title">Photographs</h2>
      </div>
      <div className="card-body">
        <div className="asset-strip">
          {activity.photos.map((photo) => (
            <figure className="asset" key={photo.id}>
              {photo.thumbnail_url && (
                <img src={photo.thumbnail_url} alt={photo.caption ?? photo.title ?? ""} />
              )}
              <figcaption className="small muted">{photo.caption ?? photo.title}</figcaption>
            </figure>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ==========================================================================
 * The brief, and doing it again
 * ======================================================================= */
function BriefButtons({ activity }: { activity: HubActivityDetail }) {
  const [showing, setShowing] = useState(false);

  const download = useAction(async () => {
    await api.download(`/activities/${activity.id}/brief.txt`);
  });

  return (
    <>
      <button className="btn" onClick={() => void download.run()} disabled={download.running}>
        {download.running ? "Preparing…" : "Download the brief"}
      </button>
      <button className="btn" onClick={() => setShowing(true)}>
        E-mail it
      </button>
      {showing && <EmailBrief activity={activity} onClose={() => setShowing(false)} />}
    </>
  );
}

function EmailBrief({ activity, onClose }: { activity: HubActivityDetail; onClose: () => void }) {
  const [to, setTo] = useState("");
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<BriefResult | null>(null);

  const send = useAction(async () => {
    const body = await api.post<BriefResult>(`/activities/${activity.id}/email`, {
      to: to
        .split(/[,\s]+/)
        .map((address) => address.trim())
        .filter(Boolean),
      message: message || null,
    });
    setResult(body);
  });

  return (
    <div className="modal-scrim" role="dialog" aria-modal="true">
      <div className="modal">
        <h2 className="modal-title">E-mail the logistics</h2>

        {result ? (
          <>
            {result.sent ? (
              <p className="strong">Sent to {result.recipients.join(", ")}.</p>
            ) : (
              <>
                {/* Not an error. A dig house with no outbound mail is a
                    supported way to run this, so the text is shown to be
                    copied rather than the whole thing being failed. */}
                <p className="strong">It could not be sent from this machine.</p>
                <p className="small muted">{result.detail}</p>
                <p className="small">Copy the text below and send it yourself.</p>
                <textarea className="input textarea mono" rows={16} readOnly value={result.brief} />
              </>
            )}
            <div className="row-tight">
              <button className="btn" onClick={onClose}>
                Close
              </button>
            </div>
          </>
        ) : (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void send.run();
            }}
          >
            {send.error && <ErrorNote message={send.error} />}
            <div className="field">
              <label className="field-label" htmlFor="brief-to">
                To
              </label>
              <input
                id="brief-to"
                className="input"
                required
                value={to}
                onChange={(event) => setTo(event.target.value)}
                placeholder="director@example.org, treasurer@example.org"
              />
              <p className="field-help">Separate several addresses with commas.</p>
            </div>
            <div className="field">
              <label className="field-label" htmlFor="brief-message">
                Anything to say first
              </label>
              <textarea
                id="brief-message"
                className="input textarea"
                rows={3}
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                placeholder="Can you sign off the vehicle hire by Friday?"
              />
            </div>
            <div className="row-tight">
              <button className="btn" type="button" onClick={onClose}>
                Cancel
              </button>
              <button className="btn btn-primary" type="submit" disabled={send.running}>
                {send.running ? "Sending…" : "Send"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

function RepeatButton({ activity }: { activity: HubActivityDetail }) {
  const navigate = useNavigate();
  const [showing, setShowing] = useState(false);
  const [startsOn, setStartsOn] = useState("");
  const [copyCosts, setCopyCosts] = useState(true);

  const repeat = useAction(async () => {
    const body = await api.post<HubActivityDetail>(`/activities/${activity.id}/repeat`, {
      starts_on: startsOn || null,
      copy_costs: copyCosts,
    });
    navigate(`/activities/${body.id}`);
  });

  return (
    <>
      <button className="btn btn-primary" onClick={() => setShowing(true)}>
        Do it again
      </button>

      {showing && (
        <div className="modal-scrim" role="dialog" aria-modal="true">
          <div className="modal">
            <h2 className="modal-title">Start the next one from this one</h2>
            <p className="small muted">
              The kit list comes across as it was, notes and all. Permissions come across needing to
              be applied for again, but remembering how long they took. Preparations come across
              unticked, with their dates worked out from the new start. Nothing about what happened
              last time is copied — the outcome stays with the season it describes, one click away.
            </p>

            <form
              onSubmit={(event) => {
                event.preventDefault();
                void repeat.run();
              }}
            >
              {repeat.error && <ErrorNote message={repeat.error} />}
              <div className="field">
                <label className="field-label" htmlFor="repeat-from">
                  Starting
                </label>
                <input
                  id="repeat-from"
                  className="input"
                  type="date"
                  value={startsOn}
                  onChange={(event) => setStartsOn(event.target.value)}
                />
                <p className="field-help">
                  {activity.duration_days
                    ? `It will run ${activity.duration_days} days, the same as last time.`
                    : "The original has no dates, so neither will this."}
                </p>
              </div>

              <div className="field">
                <label className="row-tight">
                  <input
                    className="checkbox"
                    type="checkbox"
                    checked={copyCosts}
                    onChange={(event) => setCopyCosts(event.target.checked)}
                  />
                  <span>Bring the costs across as estimates</span>
                </label>
                <p className="field-help">
                  Last year's price is an estimate of this year's, and marking it as anything else
                  is how a budget goes wrong.
                </p>
              </div>

              <div className="row-tight">
                <button className="btn" type="button" onClick={() => setShowing(false)}>
                  Cancel
                </button>
                <button className="btn btn-primary" type="submit" disabled={repeat.running}>
                  {repeat.running ? "Copying…" : "Create it"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
