import { Link } from "react-router-dom";

import { api, type Activity, type Page, type Project, type Task } from "../lib/api";
import { useQuery, useSession } from "../lib/hooks";
import { Badge, ErrorNote, Loading, PageHeader, formatDate, timeAgo } from "../components/ui";

type Counts = { projects: number; sites: number; artifacts: number; objects: number };

export function Dashboard() {
  const { user, levelIn } = useSession();
  const inArchaeology = Boolean(levelIn("archaeology"));
  const inMuseum = Boolean(levelIn("museum"));

  // One request per count, asking for a single row: the total is what is
  // wanted, and `limit=1` means the database does not assemble a page nobody
  // reads.
  const counts = useQuery<Counts>(
    async (signal) => {
      const one = { limit: 1 };
      const [projects, sites, artifacts, objects] = await Promise.all([
        inArchaeology
          ? api.get<Page<unknown>>("/projects", one, signal)
          : Promise.resolve({ total: 0 } as Page<unknown>),
        inArchaeology
          ? api.get<Page<unknown>>("/sites", one, signal)
          : Promise.resolve({ total: 0 } as Page<unknown>),
        inArchaeology
          ? api.get<Page<unknown>>("/artifacts", one, signal)
          : Promise.resolve({ total: 0 } as Page<unknown>),
        inMuseum
          ? api.get<Page<unknown>>("/museum/objects", one, signal)
          : Promise.resolve({ total: 0 } as Page<unknown>),
      ]);
      return {
        projects: projects.total,
        sites: sites.total,
        artifacts: artifacts.total,
        objects: objects.total,
      };
    },
    [inArchaeology, inMuseum],
  );

  const recent = useQuery<Page<Project>>(
    (signal) => api.get("/projects", { limit: 5, sort: "-created_at" }, signal),
    [],
    { enabled: inArchaeology },
  );

  const feed = useQuery<Page<Activity>>(
    (signal) => api.get("/activity", { limit: 12 }, signal),
    [],
  );

  // Work somebody has put on this person's list. Deliberately not gated on
  // management access: the rest of that module is closed, but your own
  // assignments are yours, and work you cannot see is work you will not do.
  const mine = useQuery<Page<Task>>(
    (signal) => api.get("/management/tasks/mine", { limit: 8 }, signal),
    [],
  );

  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const firstName = user?.full_name?.split(/\s+/)[0] ?? user?.username;

  return (
    <>
      <PageHeader
        title={`${greeting}, ${firstName}`}
        subtitle={new Date().toLocaleDateString(undefined, {
          weekday: "long",
          day: "numeric",
          month: "long",
          year: "numeric",
        })}
      />

      {/* Above the counts. Somebody opening this page wants to know what is
          being asked of them before they want to know how many finds exist. */}
      {mine.data && mine.data.items.length > 0 && (
        <section className="card" style={{ marginBottom: "var(--space-5)" }}>
          <div className="card-header">
            <span className="card-title">Assigned to you</span>
            <span className="small muted">
              {mine.data.total} {mine.data.total === 1 ? "task" : "tasks"}
            </span>
          </div>
          <div className="card-body">
            <ul className="checklist">
              {mine.data.items.map((task) => (
                <li key={task.id} className={task.days_overdue ? "provisional" : undefined}>
                  <div className="row-tight wrap">
                    <span className="strong">{task.title}</span>
                    {task.days_overdue ? (
                      <Badge
                        value="rejected"
                        kind="review"
                        label={`${task.days_overdue} ${task.days_overdue === 1 ? "day" : "days"} late`}
                      />
                    ) : null}
                    {task.priority && task.priority !== "normal" ? (
                      <Badge value={task.priority} kind="status" />
                    ) : null}
                  </div>
                  <div className="small muted">
                    {[
                      task.due_on ? `Due ${formatDate(task.due_on)}` : null,
                      task.project_name,
                      task.description,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}

      {counts.loading ? (
        <Loading rows={1} />
      ) : counts.data ? (
        <div className="stat-grid" style={{ marginBottom: "var(--space-6)" }}>
          {inArchaeology && (
            <>
              <Link to="/projects" className="stat">
                <span className="stat-value">{counts.data.projects.toLocaleString()}</span>
                <span className="stat-label">Projects</span>
              </Link>
              <Link to="/sites" className="stat">
                <span className="stat-value">{counts.data.sites.toLocaleString()}</span>
                <span className="stat-label">Sites</span>
              </Link>
              <Link to="/artifacts" className="stat">
                <span className="stat-value">{counts.data.artifacts.toLocaleString()}</span>
                <span className="stat-label">Finds</span>
              </Link>
            </>
          )}
          {inMuseum && (
            <Link to="/museum" className="stat">
              <span className="stat-value">{counts.data.objects.toLocaleString()}</span>
              <span className="stat-label">Catalogued objects</span>
            </Link>
          )}
        </div>
      ) : null}

      <div className="dashboard-columns">
        {inArchaeology && (
          <section className="card">
            <div className="card-header">
              <span className="card-title">Recent projects</span>
              <Link to="/projects" className="small">
                All projects
              </Link>
            </div>
            {recent.loading ? (
              <div className="card-body">
                <Loading rows={3} />
              </div>
            ) : recent.error ? (
              <div className="card-body">
                <ErrorNote message={recent.error} onRetry={recent.reload} />
              </div>
            ) : recent.data?.items.length ? (
              <div className="table-wrap">
                <table className="table">
                  <tbody>
                    {recent.data.items.map((project) => (
                      <tr key={project.id}>
                        <td>
                          <Link to={`/projects/${project.id}`} className="strong">
                            {project.name}
                          </Link>
                          <div className="small muted">
                            {[project.code, project.country].filter(Boolean).join(" · ")}
                          </div>
                        </td>
                        <td style={{ width: 1 }}>
                          <Badge value={project.status} kind="status" />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="card-body">
                <div className="muted small">No projects yet.</div>
              </div>
            )}
          </section>
        )}

        <section className="card">
          <div className="card-header">
            <span className="card-title">Activity</span>
          </div>
          {feed.loading ? (
            <div className="card-body">
              <Loading rows={4} />
            </div>
          ) : feed.error ? (
            <div className="card-body">
              <ErrorNote message={feed.error} onRetry={feed.reload} />
            </div>
          ) : feed.data?.items.length ? (
            <ul className="feed">
              {feed.data.items.map((entry) => (
                <li key={entry.id}>
                  <span className="feed-chip" data-action={entry.action}>
                    {(entry.resource_type ?? entry.action ?? "—").replace(/_/g, " ")}
                  </span>
                  <div style={{ minWidth: 0 }}>
                    <div className="feed-text">
                      {entry.summary ?? `${entry.action} ${entry.resource_type ?? "record"}`}
                    </div>
                    <div className="small muted">
                      {entry.user_label ?? "System"} · {timeAgo(entry.created_at)}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <div className="card-body">
              <div className="muted small">Nothing has happened yet.</div>
            </div>
          )}
        </section>
      </div>
    </>
  );
}
