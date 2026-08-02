/** Projects, sites and finds — list and detail. */

import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  api,
  type Artifact,
  type Page,
  type Project,
  type Site,
} from "../lib/api";
import { useDebounced, useQuery } from "../lib/hooks";
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
  formatRange,
  humanise,
} from "../components/ui";

const PAGE = 25;

/* --------------------------------------------------------------------------
 * Projects
 * ----------------------------------------------------------------------- */
export function Projects() {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const query = useDebounced(search);

  const { data, error, loading, reload } = useQuery<Page<Project>>(
    (signal) => api.get("/projects", { q: query, status, limit: PAGE, offset }, signal),
    [query, status, offset],
  );

  return (
    <>
      <PageHeader title="Projects" subtitle="Excavations and surveys." />

      <div className="toolbar">
        <SearchInput
          value={search}
          onChange={(value) => {
            setSearch(value);
            setOffset(0);
          }}
          placeholder="Search projects…"
        />
        <select
          className="select filter-select"
          value={status}
          onChange={(event) => {
            setStatus(event.target.value);
            setOffset(0);
          }}
        >
          <option value="">Any status</option>
          {["planned", "active", "suspended", "completed", "archived"].map((value) => (
            <option key={value} value={value}>
              {humanise(value)}
            </option>
          ))}
        </select>
      </div>

      <div className="card">
        {loading ? (
          <div className="card-body">
            <Loading />
          </div>
        ) : error ? (
          <div className="card-body">
            <ErrorNote message={error} onRetry={reload} />
          </div>
        ) : !data?.items.length ? (
          <Empty title="No projects found">
            {query || status
              ? "Nothing matches those filters."
              : "Projects appear here once somebody creates one."}
          </Empty>
        ) : (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Project</th>
                    <th>Code</th>
                    <th>Place</th>
                    <th>Dates</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((project) => (
                    <tr key={project.id}>
                      <td>
                        <Link to={`/projects/${project.id}`}>{project.name}</Link>
                        {project.institution && (
                          <div className="small muted truncate">{project.institution}</div>
                        )}
                      </td>
                      <td className="num">{project.code}</td>
                      <td className="secondary">
                        {[project.region, project.country].filter(Boolean).join(", ") || "—"}
                      </td>
                      <td className="secondary small">
                        {[formatDate(project.start_date), formatDate(project.end_date)]
                          .filter(Boolean)
                          .join(" – ") || "—"}
                      </td>
                      <td>
                        <Badge value={project.status} kind="status" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager total={data.total} limit={PAGE} offset={offset} onChange={setOffset} />
          </>
        )}
      </div>
    </>
  );
}

export function ProjectDetail() {
  // The name has to match the route's `:projectId` in App.tsx. Destructuring
  // the wrong name is silent — `id` is simply undefined, the request goes to
  // /projects/undefined, and the API rejects "undefined" as an identifier. The
  // screen then shows "Validation failed", which reads like the record is
  // broken rather than the link to it.
  const { projectId: id } = useParams<{ projectId: string }>();
  const navigate = useNavigate();

  const project = useQuery<Project>((signal) => api.get(`/projects/${id}`, undefined, signal), [id]);
  const sites = useQuery<Page<Site>>(
    (signal) => api.get("/sites", { project_id: id, limit: 100 }, signal),
    [id],
  );

  if (project.loading) return <Loading rows={6} />;
  if (project.error) return <ErrorNote message={project.error} onRetry={project.reload} />;
  if (!project.data) return null;

  const record = project.data;

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Projects", to: "/projects" }, { label: record.code }]}
        title={record.name}
        subtitle={[record.institution, record.region, record.country].filter(Boolean).join(" · ")}
        actions={
          <>
            <Badge value={record.status} kind="status" />
            <DeleteRecord
              name={record.code}
              title="Delete this project?"
              takesWithIt="its sites, their contexts and their finds"
              onDelete={() => api.delete(`/projects/${record.id}`)}
              onDeleted={() => navigate("/projects")}
            />
          </>
        }
      />

      <div className="card" style={{ marginBottom: "var(--space-4)" }}>
        <div className="card-body">
          <DetailGrid>
            <Detail label="Code" value={<span className="mono">{record.code}</span>} />
            <Detail label="Status" value={<Badge value={record.status} kind="status" />} />
            <Detail label="Country" value={record.country} />
            <Detail label="Region" value={record.region} />
            <Detail label="Institution" value={record.institution} />
            <Detail label="Starts" value={formatDate(record.start_date)} />
            <Detail label="Ends" value={formatDate(record.end_date)} />
            <Detail label="Visibility" value={record.is_public ? "Public" : "Private"} />
          </DetailGrid>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">Sites</span>
          <span className="small muted">{sites.data?.total ?? 0}</span>
        </div>
        {sites.loading ? (
          <div className="card-body">
            <Loading rows={3} />
          </div>
        ) : !sites.data?.items.length ? (
          <Empty title="No sites yet">This project has no sites recorded.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Site</th>
                  <th>Code</th>
                  <th>Type</th>
                  <th>Period</th>
                </tr>
              </thead>
              <tbody>
                {sites.data.items.map((site) => (
                  <tr key={site.id}>
                    <td>
                      <Link to={`/sites/${site.id}`}>{site.name}</Link>
                    </td>
                    <td className="num">{site.code}</td>
                    <td className="secondary">{site.site_type ? humanise(site.site_type) : "—"}</td>
                    <td className="secondary small">
                      {formatRange(site.date_from, site.date_to) ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}

/* --------------------------------------------------------------------------
 * Sites
 * ----------------------------------------------------------------------- */
export function Sites() {
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const query = useDebounced(search);

  const { data, error, loading, reload } = useQuery<Page<Site>>(
    (signal) => api.get("/sites", { q: query, limit: PAGE, offset }, signal),
    [query, offset],
  );

  return (
    <>
      <PageHeader title="Sites" subtitle="Places where work has been recorded." />

      <div className="toolbar">
        <SearchInput
          value={search}
          onChange={(value) => {
            setSearch(value);
            setOffset(0);
          }}
          placeholder="Search sites…"
        />
      </div>

      <div className="card">
        {loading ? (
          <div className="card-body">
            <Loading />
          </div>
        ) : error ? (
          <div className="card-body">
            <ErrorNote message={error} onRetry={reload} />
          </div>
        ) : !data?.items.length ? (
          <Empty title="No sites found" />
        ) : (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Site</th>
                    <th>Code</th>
                    <th>Type</th>
                    <th>Period</th>
                    <th>Position</th>
                    <th>Review</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((site) => (
                    <tr key={site.id}>
                      <td>
                        <Link to={`/sites/${site.id}`}>{site.name}</Link>
                      </td>
                      <td className="num">{site.code}</td>
                      <td className="secondary">{site.site_type ? humanise(site.site_type) : "—"}</td>
                      <td className="secondary small">
                        {formatRange(site.date_from, site.date_to) ?? "—"}
                      </td>
                      <td className="num small secondary">
                        {site.latitude != null && site.longitude != null ? (
                          <span title={site.location_restricted ? "Reduced precision" : undefined}>
                            {site.latitude.toFixed(4)}, {site.longitude.toFixed(4)}
                            {site.location_restricted && " ~"}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td>
                        <Badge value={site.review_status} kind="review" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager total={data.total} limit={PAGE} offset={offset} onChange={setOffset} />
          </>
        )}
      </div>
    </>
  );
}

export function SiteDetail() {
  const { siteId: id } = useParams<{ siteId: string }>();
  const navigate = useNavigate();

  const site = useQuery<Site & Record<string, unknown>>(
    (signal) => api.get(`/sites/${id}`, undefined, signal),
    [id],
  );
  const artifacts = useQuery<Page<Artifact>>(
    (signal) => api.get("/artifacts", { site_id: id, limit: 50 }, signal),
    [id],
  );

  if (site.loading) return <Loading rows={6} />;
  if (site.error) return <ErrorNote message={site.error} onRetry={site.reload} />;
  if (!site.data) return null;

  const record = site.data;

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Sites", to: "/sites" }, { label: record.code }]}
        title={record.name}
        subtitle={[record.site_type && humanise(record.site_type), record.country]
          .filter(Boolean)
          .join(" · ")}
        actions={
          <>
            <Badge value={record.review_status} kind="review" />
            <DeleteRecord
              name={record.code ?? record.name}
              title="Delete this site?"
              takesWithIt="its excavation contexts and its finds"
              onDelete={() => api.delete(`/sites/${record.id}`)}
              onDeleted={() => navigate("/sites")}
            />
          </>
        }
      />

      {record.location_restricted && (
        <div className="alert alert-warning" style={{ marginBottom: "var(--space-4)" }}>
          This site's location is restricted. Coordinates are shown at reduced precision to
          anyone who cannot edit the record.
        </div>
      )}

      <div className="card" style={{ marginBottom: "var(--space-4)" }}>
        <div className="card-body">
          <DetailGrid>
            <Detail label="Code" value={<span className="mono">{record.code}</span>} />
            <Detail label="Type" value={record.site_type ? humanise(record.site_type) : null} />
            <Detail label="Period" value={formatRange(record.date_from, record.date_to)} />
            <Detail label="Country" value={record.country} />
            <Detail
              label="Position"
              value={
                record.latitude != null && record.longitude != null
                  ? `${record.latitude.toFixed(5)}, ${record.longitude.toFixed(5)}`
                  : null
              }
            />
            <Detail label="Description" value={record.description as string} span={2} />
          </DetailGrid>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">Finds</span>
          <span className="small muted">{artifacts.data?.total ?? 0}</span>
        </div>
        {artifacts.loading ? (
          <div className="card-body">
            <Loading rows={3} />
          </div>
        ) : !artifacts.data?.items.length ? (
          <Empty title="No finds recorded" />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Number</th>
                  <th>Name</th>
                  <th>Condition</th>
                </tr>
              </thead>
              <tbody>
                {artifacts.data.items.map((artifact) => (
                  <tr key={artifact.id}>
                    <td className="num">
                      <Link to={`/artifacts/${artifact.id}`}>{artifact.inventory_number}</Link>
                    </td>
                    <td>{artifact.name}</td>
                    <td>
                      <Badge value={artifact.condition} kind="condition" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}

/* --------------------------------------------------------------------------
 * Finds
 * ----------------------------------------------------------------------- */
export function Artifacts() {
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const query = useDebounced(search);

  const { data, error, loading, reload } = useQuery<Page<Artifact>>(
    (signal) => api.get("/artifacts", { q: query, limit: PAGE, offset }, signal),
    [query, offset],
  );

  return (
    <>
      <PageHeader title="Finds" subtitle="Artifacts as excavated." />

      <div className="toolbar">
        <SearchInput
          value={search}
          onChange={(value) => {
            setSearch(value);
            setOffset(0);
          }}
          placeholder="Search by number or name…"
        />
      </div>

      <div className="card">
        {loading ? (
          <div className="card-body">
            <Loading />
          </div>
        ) : error ? (
          <div className="card-body">
            <ErrorNote message={error} onRetry={reload} />
          </div>
        ) : !data?.items.length ? (
          <Empty title="No finds found" />
        ) : (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Number</th>
                    <th>Name</th>
                    <th>Condition</th>
                    <th>Review</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((artifact) => (
                    <tr key={artifact.id}>
                      <td className="num">
                        <Link to={`/artifacts/${artifact.id}`}>{artifact.inventory_number}</Link>
                      </td>
                      <td>{artifact.name}</td>
                      <td>
                        <Badge value={artifact.condition} kind="condition" />
                      </td>
                      <td>
                        <Badge value={artifact.review_status} kind="review" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager total={data.total} limit={PAGE} offset={offset} onChange={setOffset} />
          </>
        )}
      </div>
    </>
  );
}

export function ArtifactDetail() {
  const { artifactId: id } = useParams<{ artifactId: string }>();
  const navigate = useNavigate();

  const artifact = useQuery<Artifact & Record<string, unknown>>(
    (signal) => api.get(`/artifacts/${id}`, undefined, signal),
    [id],
  );
  const location = useQuery<{ display_path?: string | null; legacy_location?: string | null }>(
    (signal) => api.get(`/storage/artifacts/${id}/location`, undefined, signal),
    [id],
  );

  if (artifact.loading) return <Loading rows={6} />;
  if (artifact.error) return <ErrorNote message={artifact.error} onRetry={artifact.reload} />;
  if (!artifact.data) return null;

  const record = artifact.data;

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Finds", to: "/artifacts" }, { label: record.inventory_number }]}
        title={record.name}
        subtitle={<span className="mono">{record.inventory_number}</span>}
        actions={
          <>
            <Badge value={record.condition} kind="condition" />
            <Badge value={record.review_status} kind="review" />
            <a
              className="btn btn-sm"
              href={`/api/v1/artifacts/${record.id}/qr.png`}
              target="_blank"
              rel="noreferrer"
            >
              QR label
            </a>
            <DeleteRecord
              name={record.inventory_number}
              title="Delete this find?"
              takesWithIt="its photographs and its storage history"
              onDelete={() => api.delete(`/artifacts/${record.id}`)}
              onDeleted={() => navigate("/artifacts")}
            />
          </>
        }
      />

      <div className="card">
        <div className="card-body">
          <DetailGrid>
            <Detail
              label="Inventory number"
              value={<span className="mono">{record.inventory_number}</span>}
            />
            <Detail label="Condition" value={<Badge value={record.condition} kind="condition" />} />
            <Detail label="Trench" value={record.trench as string} />
            <Detail label="Square" value={record.square as string} />
            <Detail label="Found on" value={formatDate(record.find_date as string)} />
            <Detail
              label="Where it is"
              value={location.data?.display_path ?? location.data?.legacy_location}
              span={2}
            />
            <Detail label="Description" value={record.description as string} span={2} />
          </DetailGrid>
        </div>
      </div>
    </>
  );
}
