/**
 * What has been asked for, and what has not arrived.
 *
 * The per-record panel answers "did anyone ask for the photographs of this
 * find". This answers the question somebody actually has on a Monday: what am
 * I still waiting for, and from whom. It opens on the outstanding ones,
 * because a list of everything ever asked is a list nobody reads.
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import { api, type Page } from "../lib/api";
import { useQuery, useSession } from "../lib/hooks";
import type { DataRequest } from "../components/DataRequests";
import { Empty, ErrorNote, Loading, PageHeader, formatDate, humanise } from "../components/ui";

const STATE: Record<DataRequest["status"], { label: string; className: string }> = {
  open: { label: "not sent", className: "badge-warning" },
  sent: { label: "waiting", className: "badge-info" },
  answered: { label: "files arrived", className: "badge-success" },
  closed: { label: "finished", className: "badge" },
  cancelled: { label: "withdrawn", className: "badge" },
};

export function Requests() {
  const { access } = useSession();
  const [outstanding, setOutstanding] = useState(true);
  const [mine, setMine] = useState(true);

  const requests = useQuery<Page<DataRequest>>(
    (signal) =>
      api.get("/data-requests", { outstanding: outstanding || undefined, mine, limit: 100 }, signal),
    [outstanding, mine],
  );

  const rows = requests.data?.items ?? [];

  return (
    <div>
      <PageHeader
        title="Files asked for"
        subtitle="Requests sent to people outside the platform, and whether anything has come back."
      />

      <div className="toolbar">
        <label className="chip-check">
          <input
            type="checkbox"
            checked={outstanding}
            onChange={(event) => setOutstanding(event.target.checked)}
          />
          Still waiting
        </label>
        {access?.is_platform_admin && (
          <label className="chip-check">
            <input
              type="checkbox"
              checked={!mine}
              onChange={(event) => setMine(!event.target.checked)}
            />
            Everybody&rsquo;s
          </label>
        )}
      </div>

      {requests.loading ? (
        <Loading rows={4} />
      ) : requests.error ? (
        <ErrorNote message={requests.error} onRetry={requests.reload} />
      ) : rows.length === 0 ? (
        <Empty title={outstanding ? "Nothing outstanding" : "Nothing asked for yet"}>
          {outstanding
            ? "Every request has been answered, finished or withdrawn."
            : "Open a site or a find and use “Ask somebody for files” to send somebody a link."}
        </Empty>
      ) : (
        <div className="table-wrap">
          <table className="table table-dense">
            <thead>
              <tr>
                <th>Record</th>
                <th>Asked for</th>
                <th>From</th>
                <th>State</th>
                <th>Sent</th>
                <th>Link until</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((request) => {
                const state = STATE[request.status];
                const to =
                  (request.museum_object_id && `/museum/objects/${request.museum_object_id}`) ||
                  (request.artifact_id && `/artifacts/${request.artifact_id}`) ||
                  (request.site_id && `/sites/${request.site_id}`) ||
                  (request.project_id && `/projects/${request.project_id}`) ||
                  null;
                return (
                  <tr key={request.id}>
                    <td>{to ? <Link to={to}>{request.record_label}</Link> : request.record_label}</td>
                    <td>{humanise(request.kind)}</td>
                    <td className="small">{request.recipient_name ?? request.recipient_email}</td>
                    <td>
                      <span className={`badge ${state.className}`}>{state.label}</span>
                    </td>
                    <td className="mono small">
                      {request.upload_count} / {request.max_uploads}
                    </td>
                    <td className="small">{formatDate(request.expires_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default Requests;
