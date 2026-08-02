/**
 * Importing a catalogue from a spreadsheet.
 *
 * Four screens, and the separation between them is the feature. The middle
 * one — where a person confirms, column by column, what each one fills — is
 * the whole reason this is not a single "upload" button. A column headed
 * "Date" could be the acquisition date, the date of manufacture or the date
 * somebody typed the row, and only the cataloguer knows which.
 *
 * The interface never hides a guess. Every suggested mapping is shown beside
 * real values from the file, and a column the platform could not place reads
 * "Do not import" rather than being quietly dropped into something plausible.
 */

import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, type Collection, type Page } from "../lib/api";
import { useAction, useQuery, useSession } from "../lib/hooks";
import {
  Badge,
  Empty,
  ErrorNote,
  Loading,
  PageHeader,
  formatDateTime,
} from "../components/ui";

/* --------------------------------------------------------------------------
 * Shapes
 * ----------------------------------------------------------------------- */
type ImportColumn = {
  column: string;
  suggested_field: string | null;
  field_label: string | null;
  field_kind: string | null;
  samples: string[];
  filled: number;
  total: number;
};

type AvailableField = {
  name: string;
  label: string;
  kind: string;
  required: boolean;
  help: string | null;
  value_list: string | null;
};

type Batch = {
  id: string;
  record_type: string;
  filename: string;
  sheet_name: string | null;
  header_row: number;
  status: string;
  total_rows: number;
  created_count: number;
  failed_count: number;
  created_at: string;
  columns: string[];
  mapping: Record<string, string | null>;
  defaults: Record<string, unknown>;
  columns_detail: ImportColumn[];
  unmapped_required: string[];
  available_fields: AvailableField[];
  errors: { row: number; errors: string[] }[] | null;
};

type RowResult = {
  row_number: number;
  ok: boolean;
  values: Record<string, unknown>;
  errors: string[];
  warnings: string[];
};

type Preview = {
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  rows: RowResult[];
};

/* ==========================================================================
 * 1. Upload
 * ======================================================================= */
export function ImportUpload() {
  const navigate = useNavigate();
  const { can } = useSession();
  const [file, setFile] = useState<File | null>(null);
  const [headerRow, setHeaderRow] = useState(1);
  const [dragging, setDragging] = useState(false);

  const batches = useQuery<Page<Batch>>(
    (signal) => api.get("/imports", { limit: 10 }, signal),
    [],
  );

  const upload = useAction(async (chosen: File) => {
    const data = await api.upload<{ id: string }>("/imports", chosen, {
      record_type: "museum_object",
      header_row: headerRow,
    });
    navigate(`/museum/import/${data.id}`);
  });

  if (!can("museum", "supervisor")) {
    return (
      <Empty title="Not your job, happily">
        Importing writes hundreds of records at once, so it needs supervisor access to the museum
        module. Ask whoever administers the platform.
      </Empty>
    );
  }

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Museum catalogue", to: "/museum" }, { label: "Import" }]}
        title="Import a catalogue"
        subtitle="Read a spreadsheet, check what every column means, then create the records."
      />

      {upload.error && <ErrorNote message={upload.error} />}

      <div className="col">
        <section
          className={`dropzone ${dragging ? "dragging" : ""}`}
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            const dropped = event.dataTransfer.files[0];
            if (dropped) setFile(dropped);
          }}
        >
          <svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true">
            <path
              d="M12 16V4m0 0-4 4m4-4 4 4M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <div className="empty-title">
            {file ? file.name : "Drop a spreadsheet here"}
          </div>
          <p className="small muted">
            {file
              ? `${(file.size / 1024).toFixed(0)} KB · nothing is read until you press Read the file`
              : ".xlsx or .csv. Nothing is written to the catalogue by this step."}
          </p>

          <div className="row-tight wrap" style={{ justifyContent: "center" }}>
            <label className="btn">
              {file ? "Choose another" : "Choose a file"}
              <input
                type="file"
                accept=".xlsx,.xlsm,.csv,.tsv"
                className="sr-only"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
            </label>
            <button
              type="button"
              className="btn btn-primary"
              disabled={!file || upload.running}
              onClick={() => file && void upload.run(file)}
            >
              {upload.running ? "Reading…" : "Read the file"}
            </button>
          </div>

          <label className="row-tight small muted" style={{ marginTop: 4 }}>
            Column headings are on row
            <input
              type="number"
              className="input input-sm"
              min={1}
              max={50}
              value={headerRow}
              style={{ width: "5rem" }}
              onChange={(event) => setHeaderRow(Math.max(1, Number(event.target.value) || 1))}
            />
          </label>
        </section>

        {batches.data && batches.data.items.length > 0 && (
          <section className="card">
            <div className="card-header">
              <span className="card-title">Earlier imports</span>
            </div>
            <div className="table-wrap">
              <table className="table table-dense">
                <thead>
                  <tr>
                    <th>File</th>
                    <th>When</th>
                    <th>Rows</th>
                    <th>Created</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {batches.data.items.map((batch) => (
                    <tr key={batch.id}>
                      <td>
                        <Link to={`/museum/import/${batch.id}`}>{batch.filename}</Link>
                      </td>
                      <td className="muted small">{formatDateTime(batch.created_at)}</td>
                      <td className="mono">{batch.total_rows}</td>
                      <td className="mono">{batch.created_count || "—"}</td>
                      <td>
                        <Badge value={batch.status} kind="status" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
      </div>
    </>
  );
}

/* ==========================================================================
 * 2–4. Verify, preview, commit
 * ======================================================================= */
export function ImportBatch() {
  const { batchId = "" } = useParams();
  const navigate = useNavigate();

  const batch = useQuery<Batch>(
    (signal) => api.get(`/imports/${batchId}`, undefined, signal),
    [batchId],
  );
  const collections = useQuery<Page<Collection>>(
    (signal) => api.get("/museum/collections", { limit: 200 }, signal),
    [],
  );

  const [mapping, setMapping] = useState<Record<string, string | null> | null>(null);
  const [collectionId, setCollectionId] = useState<string>("");
  const [preview, setPreview] = useState<Preview | null>(null);

  // The mapping being edited: the server's, until somebody changes something.
  const current = mapping ?? batch.data?.mapping ?? {};
  const chosenCollection =
    collectionId || (batch.data?.defaults?.collection_id as string | undefined) || "";

  /** Which fields are already spoken for, so a second column cannot take one. */
  const taken = new Set(Object.values(current).filter(Boolean) as string[]);

  const save = useAction(async () => {
    const updated = await api.patch<Batch>(`/imports/${batchId}`, {
      mapping: current,
      defaults: chosenCollection ? { collection_id: chosenCollection } : {},
    });
    setMapping(updated.mapping);
    return updated;
  });

  const check = useAction(async () => {
    await save.run();
    const result = await api.post<Preview>(`/imports/${batchId}/preview`);
    setPreview(result);
  });

  const commit = useAction(async () => {
    const result = await api.post<Preview>(`/imports/${batchId}/commit`);
    setPreview(result);
    batch.reload();
  });

  if (batch.loading) return <Loading rows={8} />;
  if (batch.error) return <ErrorNote message={batch.error} onRetry={batch.reload} />;
  if (!batch.data) return null;

  const record = batch.data;
  const committed = record.status === "committed";
  const columnsMapped = Object.values(current).filter(Boolean).length;

  return (
    <>
      <PageHeader
        breadcrumb={[
          { label: "Museum catalogue", to: "/museum" },
          { label: "Import", to: "/museum/import" },
          { label: record.filename },
        ]}
        title={record.filename}
        subtitle={
          <span className="row-tight wrap">
            <span>
              {record.total_rows.toLocaleString()} row{record.total_rows === 1 ? "" : "s"} ·{" "}
              {record.columns.length} column{record.columns.length === 1 ? "" : "s"}
            </span>
            {record.sheet_name && <span className="mono">{record.sheet_name}</span>}
            <Badge value={record.status} kind="status" />
          </span>
        }
        actions={
          committed ? (
            <Link className="btn btn-primary" to="/museum">
              Open the catalogue
            </Link>
          ) : (
            <>
              <button
                type="button"
                className="btn"
                disabled={check.running}
                onClick={() => void check.run()}
              >
                {check.running ? "Checking…" : "Check every row"}
              </button>
              <button
                type="button"
                className="btn btn-primary"
                disabled={commit.running || !preview || preview.valid_rows === 0}
                title={
                  preview
                    ? undefined
                    : "Check the rows first — nothing is written before you have seen what would happen"
                }
                onClick={() => void commit.run()}
              >
                {commit.running
                  ? "Creating…"
                  : preview
                    ? `Create ${preview.valid_rows.toLocaleString()} record${preview.valid_rows === 1 ? "" : "s"}`
                    : "Create records"}
              </button>
            </>
          )
        }
      />

      {save.error && <ErrorNote message={save.error} />}
      {check.error && <ErrorNote message={check.error} />}
      {commit.error && <ErrorNote message={commit.error} />}

      {committed ? (
        <CommitResult record={record} preview={preview} onReverted={() => navigate("/museum/import")} />
      ) : (
        <div className="col">
          {/* Which collection the objects join. Almost no file names one, and
              without it every row fails for the same reason — so it is asked
              once, here, rather than reported four thousand times. */}
          <section className="card">
            <div className="card-header">
              <span className="card-title">Applies to every row</span>
            </div>
            <div className="card-body">
              <div className="form-grid">
                <div className="form-cell" style={{ gridColumn: "span 6" }}>
                  <div className="form-label">
                    Collection <span className="required">*</span>
                  </div>
                  <select
                    className="input"
                    value={chosenCollection}
                    onChange={(event) => setCollectionId(event.target.value)}
                  >
                    <option value="">Choose a collection…</option>
                    {collections.data?.items.map((collection) => (
                      <option key={collection.id} value={collection.id}>
                        {collection.code} — {collection.name}
                      </option>
                    ))}
                  </select>
                  <div className="form-help">
                    Objects are numbered by this collection&rsquo;s own rule. A number in the file
                    that does not fit its pattern is kept and flagged, exactly as a typed one is.
                  </div>
                </div>
              </div>
            </div>
          </section>

          {/* The verification screen. */}
          <section className="card">
            <div className="card-header">
              <span className="card-title">What each column fills</span>
              <span className="small muted">
                {columnsMapped} of {record.columns.length} mapped
              </span>
            </div>

            <div className="card-body" style={{ paddingBottom: 0 }}>
              <p className="small muted" style={{ maxWidth: "70ch" }}>
                Every suggestion below is a guess, shown so you can correct it. A column set to{" "}
                <em>Do not import</em> is deliberately left out. Nothing is written to the catalogue
                until you press Create.
              </p>
            </div>

            <div className="table-wrap">
              <table className="table table-dense">
                <thead>
                  <tr>
                    <th style={{ width: "22%" }}>Column in the file</th>
                    <th style={{ width: "34%" }}>What it contains</th>
                    <th style={{ width: "28%" }}>Fills</th>
                    <th style={{ width: "16%" }}>Filled in</th>
                  </tr>
                </thead>
                <tbody>
                  {record.columns_detail.map((column) => {
                    const chosen = current[column.column] ?? null;
                    return (
                      <tr key={column.column}>
                        <td>
                          <span className="strong">{column.column}</span>
                        </td>
                        <td>
                          {column.samples.length === 0 ? (
                            <span className="muted">Every row is empty</span>
                          ) : (
                            <span className="chips">
                              {column.samples.slice(0, 3).map((sample, index) => (
                                <span key={index} className="chip sample-chip">
                                  {sample.length > 28 ? `${sample.slice(0, 28)}…` : sample}
                                </span>
                              ))}
                            </span>
                          )}
                        </td>
                        <td>
                          <select
                            className="input input-sm"
                            value={chosen ?? ""}
                            aria-label={`What ${column.column} fills`}
                            onChange={(event) =>
                              setMapping({
                                ...current,
                                [column.column]: event.target.value || null,
                              })
                            }
                          >
                            <option value="">Do not import</option>
                            {record.available_fields.map((field) => (
                              <option
                                key={field.name}
                                value={field.name}
                                // A field already filled by another column is
                                // shown but not selectable: hiding it would
                                // leave the reader wondering where it went.
                                disabled={taken.has(field.name) && field.name !== chosen}
                              >
                                {field.label}
                                {field.required ? " *" : ""}
                                {taken.has(field.name) && field.name !== chosen
                                  ? " — already mapped"
                                  : ""}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td className="mono small muted">
                          {column.filled} / {column.total}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          {preview && <PreviewReport preview={preview} />}
        </div>
      )}
    </>
  );
}

/** What every row would do, failures first. */
function PreviewReport({ preview }: { preview: Preview }) {
  return (
    <section className="card">
      <div className="card-header">
        <span className="card-title">What would happen</span>
        <span className="small muted">
          {preview.valid_rows.toLocaleString()} would import
          {preview.invalid_rows > 0 && `, ${preview.invalid_rows.toLocaleString()} would fail`}
        </span>
      </div>

      {preview.invalid_rows === 0 ? (
        <div className="card-body">
          <div className="alert alert-info">
            <span>
              <b>Every row reads cleanly.</b> {preview.valid_rows.toLocaleString()} record
              {preview.valid_rows === 1 ? "" : "s"} would be created.
            </span>
          </div>
        </div>
      ) : (
        <>
          <div className="card-body" style={{ paddingBottom: 0 }}>
            <div className="alert alert-warning">
              <span>
                <b>
                  {preview.invalid_rows.toLocaleString()} row
                  {preview.invalid_rows === 1 ? "" : "s"} would fail.
                </b>{" "}
                Row numbers are the ones in the file, so they can be found in Excel. The rest still
                import — one bad date in four thousand objects is not a reason to import none of
                them.
              </span>
            </div>
          </div>
          <div className="table-wrap">
            <table className="table table-dense">
              <thead>
                <tr>
                  <th style={{ width: "8ch" }}>Row</th>
                  <th>Why it would fail</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows
                  .filter((row) => !row.ok)
                  .map((row) => (
                    <tr key={row.row_number}>
                      <td className="mono">{row.row_number}</td>
                      <td>
                        {row.errors.map((message, index) => (
                          <div key={index}>{message}</div>
                        ))}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

/** After the run: what was created, and the way back out of it. */
function CommitResult({
  record,
  preview,
  onReverted,
}: {
  record: Batch;
  preview: Preview | null;
  onReverted: () => void;
}) {
  const [confirming, setConfirming] = useState(false);

  const revert = useAction(async () => {
    const result = await api.delete<{ detail: string }>(`/imports/${record.id}/records`);
    setConfirming(false);
    onReverted();
    return result;
  });

  return (
    <div className="col">
      <section className="card">
        <div className="card-body">
          <div className="stat-grid">
            <div className="stat">
              <span className="stat-value" style={{ color: "var(--ok)" }}>
                {record.created_count.toLocaleString()}
              </span>
              <span className="stat-label">Created</span>
            </div>
            <div className="stat">
              <span
                className="stat-value"
                style={{ color: record.failed_count ? "var(--warn)" : undefined }}
              >
                {record.failed_count.toLocaleString()}
              </span>
              <span className="stat-label">Skipped</span>
            </div>
            <div className="stat">
              <span className="stat-value">{record.total_rows.toLocaleString()}</span>
              <span className="stat-label">Rows in the file</span>
            </div>
          </div>
        </div>
      </section>

      {record.errors && record.errors.length > 0 && (
        <section className="card">
          <div className="card-header">
            <span className="card-title">Rows that were skipped</span>
          </div>
          <div className="table-wrap">
            <table className="table table-dense">
              <thead>
                <tr>
                  <th style={{ width: "8ch" }}>Row</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {record.errors.map((entry) => (
                  <tr key={entry.row}>
                    <td className="mono">{entry.row}</td>
                    <td>
                      {entry.errors.map((message, index) => (
                        <div key={index}>{message}</div>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {preview && preview.rows.some((row) => row.ok) && (
        <p className="small muted">
          The import is recorded with the mapping you approved, so months from now it is possible to
          answer where these records came from.
        </p>
      )}

      <section className="card">
        <div className="card-body">
          <div className="row-between wrap">
            <div>
              <div className="strong">Undo this import</div>
              <p className="small muted" style={{ maxWidth: "60ch" }}>
                Deletes the records this run created, and nothing else. A record somebody has edited
                since is kept — they have worked on it, and undoing the import should not discard
                that.
              </p>
            </div>
            {confirming ? (
              <div className="row-tight">
                <button type="button" className="btn" onClick={() => setConfirming(false)}>
                  Keep them
                </button>
                <button
                  type="button"
                  className="btn btn-danger-solid"
                  disabled={revert.running}
                  onClick={() => void revert.run()}
                >
                  {revert.running
                    ? "Deleting…"
                    : `Delete ${record.created_count.toLocaleString()} records`}
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="btn btn-danger"
                disabled={record.created_count === 0}
                onClick={() => setConfirming(true)}
              >
                Undo…
              </button>
            )}
          </div>
          {revert.error && <ErrorNote message={revert.error} />}
        </div>
      </section>
    </div>
  );
}
