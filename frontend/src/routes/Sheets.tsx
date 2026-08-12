/**
 * The sheet room: every spreadsheet the institution holds.
 *
 * A file that arrived is a document in its own right, not a step in an import
 * that stops mattering once the records exist. Somebody will ask for "the finds
 * register as Ahmad sent it in March" long after those records have been
 * corrected forty times, and the only honest answer is the file itself.
 *
 * So each sheet is here twice, and the screen never lets the two be confused:
 *
 * **As it arrived** — byte for byte, never rewritten. It is the evidence.
 *
 * **Up to date** — the same records as they stand now, in the *sheet's own*
 * columns and headings. That last part is the whole point. A register that
 * comes back with columns called `inventory_number` and `period_id` is a
 * register somebody has to re-key before sending it to a ministry, which is
 * exactly the work the platform was supposed to save.
 *
 * Removing a sheet is archiving it. Nothing here deletes a file.
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import { api, type Page } from "../lib/api";
import { useAction, useQuery, useSession } from "../lib/hooks";
import {
  Badge,
  Empty,
  ErrorNote,
  Loading,
  PageHeader,
  SearchInput,
  formatDate,
  formatDateTime,
  humanise,
} from "../components/ui";

export type Sheet = {
  id: string;
  record_type: string;
  filename: string;
  sheet_name?: string | null;
  status: string;
  state: string;
  total_rows: number;
  created_count: number;
  failed_count: number;
  created_at: string;
  is_archived: boolean;
  superseded_by_id?: string | null;
  refreshed_at?: string | null;
  has_current_copy: boolean;
  owner_label?: string | null;
};

/** What each state means, said once here rather than guessed at on the screen. */
const STATES: Record<string, { label: string; tone: string; means: string }> = {
  received: {
    label: "Received",
    tone: "temporary",
    means: "On the shelf. Nothing has been read into the platform from it yet.",
  },
  imported: {
    label: "Imported",
    tone: "active",
    means: "Its rows are records on the platform, and can be brought back out up to date.",
  },
  superseded: {
    label: "Replaced",
    tone: "archived",
    means: "A newer version of this sheet arrived. Kept, because what was received matters.",
  },
  archived: {
    label: "Put away",
    tone: "archived",
    means: "Out of the working list. The file is still here and still downloadable.",
  },
  failed: {
    label: "Would not read",
    tone: "missing",
    means: "The platform could not read it. The file is kept as it arrived.",
  },
};

export function Sheets() {
  const { can } = useSession();
  const mayManage = can("archaeology", "supervisor") || can("museum", "supervisor");

  const [term, setTerm] = useState("");
  const [state, setState] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [chosen, setChosen] = useState<string[]>([]);

  const sheets = useQuery<Page<Sheet>>(
    (signal) =>
      api.get(
        "/imports",
        {
          q: term || undefined,
          state: state || undefined,
          include_archived: showArchived || undefined,
          limit: 100,
        },
        signal,
      ),
    [term, state, showArchived],
  );

  const rows = sheets.data?.items ?? [];

  return (
    <>
      <PageHeader
        title="Sheets"
        subtitle="Every spreadsheet the institution holds, as it arrived and as it stands now"
        actions={
          mayManage && (
            <Link className="btn btn-primary" to="/import">
              Add a sheet
            </Link>
          )
        }
      />

      <div className="toolbar">
        <SearchInput value={term} onChange={setTerm} placeholder="File name…" />
        <select
          className="input input-sm"
          value={state}
          onChange={(event) => setState(event.target.value)}
        >
          <option value="">Any state</option>
          {Object.entries(STATES).map(([key, meaning]) => (
            <option key={key} value={key}>
              {meaning.label}
            </option>
          ))}
        </select>
        <label className="checkbox small">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(event) => setShowArchived(event.target.checked)}
          />
          Include the ones put away
        </label>
      </div>

      {chosen.length > 0 && (
        <div className="alert alert-info">
          <b>{chosen.length} chosen.</b>{" "}
          <Link className="btn btn-sm btn-primary" to={`/outgoing?sheets=${chosen.join(",")}`}>
            Send these to somebody
          </Link>{" "}
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setChosen([])}>
            Clear
          </button>
        </div>
      )}

      {sheets.loading ? (
        <Loading rows={5} />
      ) : sheets.error ? (
        <ErrorNote message={sheets.error} onRetry={sheets.reload} />
      ) : rows.length === 0 ? (
        <Empty title="No sheets here yet">
          Spreadsheets appear here as soon as they are uploaded — whether or not anything
          has been read into the platform from them.
        </Empty>
      ) : (
        rows.map((sheet) => (
          <SheetRow
            key={sheet.id}
            sheet={sheet}
            chosen={chosen.includes(sheet.id)}
            mayManage={mayManage}
            onPick={() =>
              setChosen((current) =>
                current.includes(sheet.id)
                  ? current.filter((id) => id !== sheet.id)
                  : [...current, sheet.id],
              )
            }
            onChanged={() => sheets.reload()}
          />
        ))
      )}
    </>
  );
}

function SheetRow({
  sheet,
  chosen,
  mayManage,
  onPick,
  onChanged,
}: {
  sheet: Sheet;
  chosen: boolean;
  mayManage: boolean;
  onPick: () => void;
  onChanged: () => void;
}) {
  const meaning = STATES[sheet.state] ?? {
    label: sheet.state,
    tone: "archived",
    means: "",
  };

  const refresh = useAction(async () => {
    await api.post(`/imports/${sheet.id}/refresh`, {});
    onChanged();
  });

  const shelve = useAction(async (archived: boolean) => {
    await api.patch(`/imports/${sheet.id}/shelf`, { is_archived: archived });
    onChanged();
  });

  return (
    <section className="card" style={{ marginBottom: 12 }}>
      <div className="card-body">
        <div className="row-tight" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
          <div style={{ minWidth: 0 }}>
            <label className="checkbox small" style={{ marginBottom: 4 }}>
              <input type="checkbox" checked={chosen} onChange={onPick} />
              <span className="strong">{sheet.filename}</span>
            </label>
            <div className="muted small">
              {humanise(sheet.record_type)} · {sheet.total_rows} row
              {sheet.total_rows === 1 ? "" : "s"}
              {sheet.created_count > 0 && ` · ${sheet.created_count} records made`}
              {" · "}
              {formatDate(sheet.created_at)}
              {sheet.owner_label && ` · ${sheet.owner_label}`}
            </div>
            <div className="muted small">{meaning.means}</div>
          </div>

          <div style={{ textAlign: "right" }}>
            <Badge value={meaning.tone} kind="status" label={meaning.label} />
          </div>
        </div>

        {refresh.error && <ErrorNote message={refresh.error} />}
        {shelve.error && <ErrorNote message={shelve.error} />}

        <div className="row-tight" style={{ marginTop: 10, flexWrap: "wrap" }}>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() =>
              void api.download(`/imports/${sheet.id}/original`, undefined, sheet.filename)
            }
          >
            As it arrived
          </button>

          {sheet.has_current_copy && (
            <button
              type="button"
              className="btn btn-sm"
              onClick={() =>
                void api.download(
                  `/imports/${sheet.id}/current.xlsx`,
                  undefined,
                  `${sheet.filename.replace(/\.[^.]+$/, "")} (up to date).xlsx`,
                )
              }
            >
              Up to date
              {sheet.refreshed_at && (
                <span className="muted"> · {formatDateTime(sheet.refreshed_at)}</span>
              )}
            </button>
          )}

          {mayManage && sheet.created_count > 0 && (
            <button
              type="button"
              className="btn btn-sm"
              disabled={refresh.running}
              title="Rebuilds the sheet from the records, in this sheet's own columns. The original is untouched."
              onClick={() => void refresh.run()}
            >
              {refresh.running
                ? "Bringing it up to date…"
                : sheet.has_current_copy
                  ? "Bring it up to date again"
                  : "Bring it up to date"}
            </button>
          )}

          <Link className="btn btn-ghost btn-sm" to={`/import?batch=${sheet.id}`}>
            How it was mapped
          </Link>

          {mayManage && (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={shelve.running}
              title="Nothing is deleted — it comes out of the working list"
              onClick={() => void shelve.run(!sheet.is_archived)}
            >
              {sheet.is_archived ? "Put it back" : "Put it away"}
            </button>
          )}
        </div>
      </div>
    </section>
  );
}

export default Sheets;
