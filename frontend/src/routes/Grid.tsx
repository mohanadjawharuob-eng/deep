/**
 * The catalogue as a spreadsheet.
 *
 * A cataloguer correcting one field across forty objects should not open
 * forty record cards. This is the same records in the shape they arrived in —
 * a grid you tab through, type into, and paste into — with the platform's
 * rules still applied to every cell.
 *
 * Three things make it a spreadsheet rather than a table of inputs:
 *
 * - **Keyboard first.** Arrow keys move, Enter and Tab commit and move on,
 *   Escape abandons the cell. Typing over a selected cell replaces it, which
 *   is what every spreadsheet does and what fingers expect.
 * - **Nothing saves until you say so.** Edits collect as a visible pile of
 *   changes; Save sends them and reports what happened per row. Autosaving a
 *   grid is how somebody's stray keystroke becomes four hundred corrections.
 * - **Which columns are shown is a choice.** The record has fifty-two fields.
 *   Showing all of them is unusable; the interesting six change with the task.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api, type Collection, type FormField, type FormLayout, type Page } from "../lib/api";
import { useAction, useDebounced, useQuery, useSession } from "../lib/hooks";
import { layoutFields } from "../components/RecordCard";
import {
  Empty,
  ErrorNote,
  LegacyMark,
  Loading,
  PageHeader,
  SearchInput,
  humanise,
} from "../components/ui";

const PAGE = 100;

/** Fields the backend refuses to change through a field edit, by design. */
const LOCKED = new Set(["accession_number", "collection_id", "number_is_legacy"]);

/** What a grid opens with. The rest are a column away, not a rebuild away. */
const DEFAULT_COLUMNS = [
  "accession_number",
  "title",
  "object_type",
  "materials",
  "condition",
  "status",
  "storage_location_id",
];

type Row = Record<string, unknown> & { id: string };

/** One pending change: which row, which field, what it should become. */
type Edit = { rowId: string; field: string; value: unknown };

export function CatalogueGrid() {
  const { can } = useSession();
  const mayEdit = can("museum", "contributor");

  const [params, setParams] = useSearchParams();
  const [term, setTerm] = useState(params.get("q") ?? "");
  const debounced = useDebounced(term);
  const collectionId = params.get("collection_id") ?? "";
  const offset = Number(params.get("offset") ?? 0);

  const layout = useQuery<FormLayout>(
    (signal) => api.get("/forms/layouts/museum_object", undefined, signal),
    [],
  );
  const collections = useQuery<Page<Collection>>(
    (signal) => api.get("/museum/collections", { limit: 200 }, signal),
    [],
  );
  // `/objects/grid`, not `/objects`: the list endpoint returns a summary of a
  // dozen fields, so any column beyond those would draw a row of em-dashes and
  // look exactly like a field nobody has filled in.
  const rows = useQuery<Page<Row>>(
    (signal) =>
      api.get(
        "/museum/objects/grid",
        {
          q: debounced || undefined,
          collection_id: collectionId || undefined,
          limit: PAGE,
          offset,
        },
        signal,
      ),
    [debounced, collectionId, offset],
  );

  const [columns, setColumns] = useState<string[]>(DEFAULT_COLUMNS);
  const [picking, setPicking] = useState(false);
  const [edits, setEdits] = useState<Edit[]>([]);
  const [cursor, setCursor] = useState<{ row: number; col: number } | null>(null);
  const [typing, setTyping] = useState(false);
  const [failures, setFailures] = useState<{ number: string; reason: string }[]>([]);

  const fields = useMemo(() => {
    if (!layout.data) return new Map<string, FormField>();
    return new Map(layoutFields(layout.data).map((field) => [field.name, field]));
  }, [layout.data]);

  const data = rows.data?.items ?? [];

  /** The value a cell should show: the pending edit if there is one. */
  const valueOf = useCallback(
    (row: Row, field: string) => {
      const edit = edits.find((item) => item.rowId === row.id && item.field === field);
      return edit ? edit.value : row[field];
    },
    [edits],
  );

  const isEdited = useCallback(
    (rowId: string, field: string) =>
      edits.some((item) => item.rowId === rowId && item.field === field),
    [edits],
  );

  const setCell = (rowId: string, field: string, value: unknown) => {
    setEdits((current) => {
      const rest = current.filter((item) => !(item.rowId === rowId && item.field === field));
      const original = data.find((row) => row.id === rowId)?.[field];

      // Typing a value back to what it already was is not a change. Without
      // this, undoing an edit by hand still counts towards the save, and the
      // count of pending changes stops meaning anything.
      const same =
        JSON.stringify(original ?? null) === JSON.stringify(value ?? null);
      return same ? rest : [...rest, { rowId, field, value }];
    });
  };

  const download = useAction(() =>
    api.download(
      "/museum/objects/export.csv",
      {
        q: debounced || undefined,
        collection_id: collectionId || undefined,
        columns: columns.join(","),
      },
      "catalogue.csv",
    ),
  );

  const save = useAction(async () => {
    const byRow = new Map<string, Record<string, unknown>>();
    for (const edit of edits) {
      const patch = byRow.get(edit.rowId) ?? {};
      patch[edit.field] = edit.value;
      byRow.set(edit.rowId, patch);
    }

    const failed: { number: string; reason: string }[] = [];
    for (const [rowId, patch] of byRow) {
      try {
        await api.patch(`/museum/objects/${rowId}`, patch);
      } catch (cause) {
        const row = data.find((item) => item.id === rowId);
        failed.push({
          number: String(row?.accession_number ?? rowId),
          reason: cause instanceof Error ? cause.message : "Refused",
        });
      }
    }

    // Only the rows that failed keep their pending edits, so pressing Save
    // again retries exactly those and nothing else.
    setEdits((current) =>
      current.filter((edit) => {
        const row = data.find((item) => item.id === edit.rowId);
        return failed.some((entry) => entry.number === String(row?.accession_number));
      }),
    );
    setFailures(failed);
    rows.reload();
  });

  // Leaving with unsaved work is almost always an accident.
  useEffect(() => {
    if (edits.length === 0) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [edits.length]);

  const move = (rowDelta: number, colDelta: number) => {
    setCursor((current) => {
      if (!current) return { row: 0, col: 0 };
      return {
        row: Math.min(data.length - 1, Math.max(0, current.row + rowDelta)),
        col: Math.min(columns.length - 1, Math.max(0, current.col + colDelta)),
      };
    });
    setTyping(false);
  };

  if (layout.loading) return <Loading rows={8} />;
  if (layout.error) return <ErrorNote message={layout.error} onRetry={layout.reload} />;

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Museum catalogue", to: "/museum" }, { label: "Grid" }]}
        title="Catalogue grid"
        subtitle={
          rows.data
            ? `${rows.data.total.toLocaleString()} object${rows.data.total === 1 ? "" : "s"} · ${columns.length} columns shown`
            : "The catalogue as a spreadsheet"
        }
        actions={
          <>
            <Link className="btn btn-sm" to="/museum">
              List view
            </Link>
            <button type="button" className="btn btn-sm" onClick={() => setPicking((open) => !open)}>
              Columns
            </button>
            <button
              type="button"
              className="btn btn-sm"
              disabled={download.running}
              onClick={() => void download.run()}
            >
              {download.running ? "Preparing…" : "Download as CSV"}
            </button>
            {mayEdit && edits.length > 0 && (
              <>
                <span className="small strong" style={{ color: "var(--warn)" }}>
                  {edits.length} change{edits.length === 1 ? "" : "s"}
                </span>
                <button type="button" className="btn" onClick={() => setEdits([])}>
                  Discard
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={save.running}
                  onClick={() => void save.run()}
                >
                  {save.running ? "Saving…" : "Save"}
                </button>
              </>
            )}
          </>
        }
      />

      {save.error && <ErrorNote message={save.error} />}
      {download.error && <ErrorNote message={download.error} />}
      {failures.length > 0 && (
        <div className="alert alert-warning" style={{ marginBottom: "var(--space-4)" }}>
          <div>
            <b>
              {failures.length} row{failures.length === 1 ? "" : "s"} were refused
            </b>{" "}
            and keep their changes, so pressing Save again retries just those.
            <ul style={{ margin: "6px 0 0 18px" }}>
              {failures.slice(0, 6).map((entry) => (
                <li key={entry.number} className="small">
                  <span className="mono">{entry.number}</span> — {entry.reason}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <div className="toolbar">
        <SearchInput value={term} onChange={setTerm} placeholder="Filter the grid…" />
        <select
          className="input input-sm filter-select"
          value={collectionId}
          onChange={(event) => {
            const next = new URLSearchParams(params);
            if (event.target.value) next.set("collection_id", event.target.value);
            else next.delete("collection_id");
            next.delete("offset");
            setParams(next);
          }}
        >
          <option value="">All collections</option>
          {collections.data?.items.map((collection) => (
            <option key={collection.id} value={collection.id}>
              {collection.name}
            </option>
          ))}
        </select>
        {mayEdit && (
          <span className="small muted">
            Click a cell and type. Arrows move, Enter commits, Escape undoes.
          </span>
        )}
      </div>

      {picking && layout.data && (
        <ColumnPicker
          all={layoutFields(layout.data)}
          chosen={columns}
          onChange={setColumns}
          onClose={() => setPicking(false)}
        />
      )}

      {rows.loading ? (
        <Loading />
      ) : rows.error ? (
        <ErrorNote message={rows.error} onRetry={rows.reload} />
      ) : data.length === 0 ? (
        <Empty title="Nothing to show">
          No object matches. Clear the filter, or add one from the list view.
        </Empty>
      ) : (
        <div className="grid-wrap card">
          <table className="grid">
            <thead>
              <tr>
                <th className="grid-gutter" />
                {columns.map((name) => {
                  const field = fields.get(name);
                  return (
                    <th key={name} title={field?.help ?? undefined}>
                      {field?.label ?? humanise(name)}
                      {LOCKED.has(name) && (
                        <span className="grid-lock" title="Not editable here">
                          🔒
                        </span>
                      )}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {data.map((row, rowIndex) => (
                <tr key={row.id}>
                  <td className="grid-gutter">
                    <Link
                      to={`/museum/objects/${row.id}`}
                      className="small muted"
                      title="Open the full record"
                    >
                      {rowIndex + 1 + offset}
                    </Link>
                  </td>
                  {columns.map((name, colIndex) => (
                    <GridCell
                      key={name}
                      layout={layout.data!}
                      field={fields.get(name)}
                      name={name}
                      value={valueOf(row, name)}
                      edited={isEdited(row.id, name)}
                      locked={!mayEdit || LOCKED.has(name)}
                      active={cursor?.row === rowIndex && cursor?.col === colIndex}
                      typing={typing && cursor?.row === rowIndex && cursor?.col === colIndex}
                      row={row}
                      onFocus={() => {
                        setCursor({ row: rowIndex, col: colIndex });
                        setTyping(false);
                      }}
                      onType={() => setTyping(true)}
                      onCommit={(value) => {
                        setCell(row.id, name, value);
                        setTyping(false);
                      }}
                      onMove={move}
                    />
                  ))}
                </tr>
              ))}
            </tbody>
          </table>

          {rows.data && rows.data.total > PAGE && (
            <div className="pager">
              <span className="small muted">
                {offset + 1}–{Math.min(offset + PAGE, rows.data.total)} of{" "}
                {rows.data.total.toLocaleString()}
              </span>
              <div className="row-tight">
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={offset === 0 || edits.length > 0}
                  title={edits.length > 0 ? "Save or discard your changes first" : undefined}
                  onClick={() => {
                    const next = new URLSearchParams(params);
                    next.set("offset", String(Math.max(0, offset - PAGE)));
                    setParams(next);
                  }}
                >
                  Previous
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={offset + PAGE >= rows.data.total || edits.length > 0}
                  title={edits.length > 0 ? "Save or discard your changes first" : undefined}
                  onClick={() => {
                    const next = new URLSearchParams(params);
                    next.set("offset", String(offset + PAGE));
                    setParams(next);
                  }}
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </>
  );
}

/* --------------------------------------------------------------------------
 * One cell
 * ----------------------------------------------------------------------- */
function GridCell({
  layout,
  field,
  name,
  value,
  edited,
  locked,
  active,
  typing,
  row,
  onFocus,
  onType,
  onCommit,
  onMove,
}: {
  layout: FormLayout;
  field: FormField | undefined;
  name: string;
  value: unknown;
  edited: boolean;
  locked: boolean;
  active: boolean;
  typing: boolean;
  row: Row;
  onFocus: () => void;
  onType: () => void;
  onCommit: (value: unknown) => void;
  onMove: (rowDelta: number, colDelta: number) => void;
}) {
  const cell = useRef<HTMLTableCellElement>(null);
  const input = useRef<HTMLInputElement | HTMLSelectElement>(null);
  const [draft, setDraft] = useState("");

  const options = field?.value_list ? (layout.value_list_options[field.value_list] ?? []) : [];

  useEffect(() => {
    if (active && !typing) cell.current?.focus();
    if (typing) input.current?.focus();
  }, [active, typing]);

  /** One value, as a label rather than whatever the database stores. */
  const label = (item: unknown): string => {
    if (item === null || item === undefined || item === "") return "";
    if (typeof item === "boolean") return item ? "Yes" : "No";
    const match = options.find((option) => option.value === String(item));
    return match ? match.label : String(item);
  };

  const display = () => {
    if (value === null || value === undefined || value === "") return "";
    // Item by item. Joining first is the obvious shortcut and leaves a
    // materials cell reading "79c43041-6fe5-…" where it should read "Bronze".
    if (Array.isArray(value)) return value.map(label).filter(Boolean).join(", ");
    return label(value);
  };

  const begin = (seed?: string) => {
    if (locked) return;
    setDraft(seed ?? display());
    onType();
  };

  /** A label the person typed, back to the value the database stores. */
  const toValue = (typed: string) => {
    const match = options.find(
      (option) => option.label.toLowerCase() === typed.toLowerCase(),
    );
    return match ? match.value : typed;
  };

  const commit = (raw: string) => {
    if (!field) return onCommit(raw || null);

    // The same shapes the record card sends, so a value typed in the grid and
    // the same value typed on the card reach the backend identically.
    if (field.kind === "multiselect" || field.kind === "tags") {
      const items = raw
        .split(/[;,]/)
        .map((part) => part.trim())
        .filter(Boolean)
        .map(toValue);
      return onCommit(items.length ? items : null);
    }
    if (field.kind === "number" || field.kind === "integer") {
      if (raw.trim() === "") return onCommit(null);
      const parsed = Number(raw);
      return onCommit(Number.isFinite(parsed) ? parsed : raw);
    }
    if (field.kind === "boolean") return onCommit(/^(y|yes|true|1)$/i.test(raw.trim()));
    return onCommit(raw.trim() === "" ? null : toValue(raw.trim()));
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (typing) {
      if (event.key === "Escape") {
        event.preventDefault();
        setDraft("");
        onCommit(value);
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        commit(draft);
        onMove(1, 0);
        return;
      }
      if (event.key === "Tab") {
        event.preventDefault();
        commit(draft);
        onMove(0, event.shiftKey ? -1 : 1);
        return;
      }
      return;
    }

    switch (event.key) {
      case "ArrowDown": event.preventDefault(); onMove(1, 0); break;
      case "ArrowUp": event.preventDefault(); onMove(-1, 0); break;
      case "ArrowRight": event.preventDefault(); onMove(0, 1); break;
      case "ArrowLeft": event.preventDefault(); onMove(0, -1); break;
      case "Tab": event.preventDefault(); onMove(0, event.shiftKey ? -1 : 1); break;
      case "Enter": event.preventDefault(); begin(); break;
      case "Backspace":
      case "Delete": event.preventDefault(); onCommit(null); break;
      default:
        // Typing over a selected cell replaces it, as every spreadsheet does.
        if (event.key.length === 1 && !event.ctrlKey && !event.metaKey) {
          event.preventDefault();
          begin(event.key);
        }
    }
  };

  const className = [
    "grid-cell",
    edited && "edited",
    locked && "locked",
    active && "active",
    field && (field.kind === "number" || field.kind === "integer") && "numeric",
    name === "accession_number" && "mono",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <td
      ref={cell}
      className={className}
      tabIndex={active ? 0 : -1}
      // Only when the cell itself is the target. React's onFocus is focusin,
      // which bubbles — so without this guard, opening the editor focuses the
      // input, the input's focus reaches this handler, and the handler closes
      // the editor it just opened. Typing would appear to do nothing at all.
      onFocus={(event) => {
        if (event.target === event.currentTarget) onFocus();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onFocus();
      }}
      onDoubleClick={() => begin()}
      onKeyDown={onKeyDown}
      title={locked ? "Change this on the record card" : undefined}
    >
      {typing ? (
        // A dropdown only where the field holds one value. Offering one for a
        // multiselect would quietly replace "bronze and bone" with "bone".
        options.length && field?.kind !== "multiselect" && field?.kind !== "tags" ? (
          <select
            ref={input as React.RefObject<HTMLSelectElement>}
            className="grid-input"
            value={String(value ?? "")}
            onChange={(event) => {
              onCommit(event.target.value || null);
              onMove(1, 0);
            }}
            onBlur={() => onCommit(value)}
          >
            <option value="">—</option>
            {options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        ) : (
          <input
            ref={input as React.RefObject<HTMLInputElement>}
            className="grid-input"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onBlur={() => commit(draft)}
          />
        )
      ) : (
        <>
          {display() || <span className="grid-empty">—</span>}
          {name === "accession_number" && row.number_is_legacy === true && <LegacyMark />}
        </>
      )}
    </td>
  );
}

/* --------------------------------------------------------------------------
 * Choosing columns
 * ----------------------------------------------------------------------- */
function ColumnPicker({
  all,
  chosen,
  onChange,
  onClose,
}: {
  all: FormField[];
  chosen: string[];
  onChange: (columns: string[]) => void;
  onClose: () => void;
}) {
  const toggle = (name: string) =>
    onChange(
      chosen.includes(name) ? chosen.filter((item) => item !== name) : [...chosen, name],
    );

  return (
    <section className="card" style={{ marginBottom: "var(--space-4)" }}>
      <div className="card-header">
        <span className="card-title">Columns</span>
        <div className="row-tight">
          <button type="button" className="btn btn-sm" onClick={() => onChange(DEFAULT_COLUMNS)}>
            Reset
          </button>
          <button type="button" className="btn btn-sm" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
      <div className="card-body">
        <p className="small muted" style={{ marginBottom: 10 }}>
          The record holds {all.length} fields. Show the ones this job needs — the order you tick
          them is the order they appear.
        </p>
        <div className="column-picker">
          {all.map((field) => (
            <label key={field.name} className="checkbox small">
              <input
                type="checkbox"
                checked={chosen.includes(field.name)}
                onChange={() => toggle(field.name)}
              />
              {field.label}
            </label>
          ))}
        </div>
      </div>
    </section>
  );
}
