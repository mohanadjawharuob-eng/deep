/**
 * Registering a tray of forty.
 *
 * The platform has always been able to record one find at a time and to read a
 * spreadsheet of four thousand. The unit archaeology actually works in is
 * neither: it is a tray of forty bags on a finds table, all from one context,
 * washed on one afternoon, differing in four columns and identical in the rest.
 * Doing that one record card at a time means re-choosing the site and the
 * context forty times, so in practice people open Excel — and then the platform
 * is not where the work happens, it is where the work is eventually filed.
 *
 * So: type the tray. Everything the forty share is set once at the top;
 * everything that differs is a column you type down. Which fields go where is
 * the whole interface, because that split is what makes the tray a tray.
 *
 * **It writes nothing.** When the rows are typed they are handed to the
 * importer as if they had been a file, and the importer's existing screens take
 * over: check every row, see what is wrong before anything is written, commit,
 * and — if the tray turns out to be wrong — undo the whole thing in one action.
 * That reuse is the reason this screen is small, and the reason a typed tray is
 * exactly as safe as an imported one. Nothing here can write a record that an
 * import could not, and nothing here bypasses a check an import would make.
 */

import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { api, type FormField, type FormLayout } from "../lib/api";
import { useAction, useQuery, useSession } from "../lib/hooks";
import { Empty, ErrorNote, Loading, PageHeader } from "../components/ui";
import { KINDS, PARENT } from "./Import";

/** How many blank rows a tray starts with, and how many "more rows" adds. */
const ROWS = 12;

/* --------------------------------------------------------------------------
 * Turning typed rows into a file
 * ----------------------------------------------------------------------- */

/**
 * One CSV cell.
 *
 * A find called `Bowl, carinated` and a description containing a line break
 * are both ordinary, and both destroy a naively joined CSV. Quote anything
 * with a comma, a quote or a newline, and double the quotes inside it —
 * RFC 4180, which is what the reader on the other end expects.
 */
function cell(value: string): string {
  return /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

function toCsv(headers: string[], rows: string[][]): string {
  return [headers, ...rows].map((row) => row.map(cell).join(",")).join("\r\n");
}

/**
 * Column headings, guaranteed distinct.
 *
 * Two fields may share a label across groups, and the importer refuses a file
 * whose columns collide — correctly, because it could not then tell you which
 * one it was reading. Numbering the second one keeps the heading readable and
 * the mapping unambiguous.
 */
function headingsFor(fields: FormField[]): string[] {
  const used = new Map<string, number>();
  return fields.map((field) => {
    const seen = used.get(field.label) ?? 0;
    used.set(field.label, seen + 1);
    return seen === 0 ? field.label : `${field.label} (${seen + 1})`;
  });
}

/* --------------------------------------------------------------------------
 * Which fields start where
 * ----------------------------------------------------------------------- */

function allFields(layout: FormLayout): FormField[] {
  return layout.tabs.flatMap((tab) => tab.groups.flatMap((group) => group.fields));
}

/**
 * A first guess at the split, which the person then corrects.
 *
 * Shared: whatever the importer already asks once for a whole file — the site,
 * the collection — because a tray is one file's worth of rows by another name.
 *
 * Columns: the ones the layout marks `in_tray`, which is the layout saying
 * "these are the columns a register of these records always has". Required
 * fields are added whether or not they are marked, because a tray that cannot
 * be saved without leaving the screen to add a column is a worse first
 * impression than one column too many.
 */
function firstGuess(layout: FormLayout, recordType: string) {
  const fields = allFields(layout).filter((field) => !field.read_only);
  const parent = PARENT[recordType]?.field;

  const shared = fields.filter((field) => field.name === parent).map((field) => field.name);

  const columns: string[] = [];
  const take = (field: FormField) => {
    if (!columns.includes(field.name) && !shared.includes(field.name)) columns.push(field.name);
  };

  const key = fields.find((field) => field.name === layout.key_field);
  if (key) take(key);
  fields.filter((field) => field.required).forEach(take);
  fields.filter((field) => field.in_tray).forEach(take);

  return { shared, columns };
}

/* ==========================================================================
 * The screen
 * ======================================================================= */
export function BatchEntry() {
  const navigate = useNavigate();
  const { can } = useSession();
  const [params, setParams] = useSearchParams();

  const allowed = KINDS.filter((kind) => can(kind.module, "supervisor"));
  const requested = params.get("type") ?? "";
  const kind = allowed.find((item) => item.value === requested) ?? allowed[0];
  const recordType = kind?.value ?? "";

  const layout = useQuery<FormLayout>(
    (signal) => api.get(`/forms/layouts/${recordType}`, undefined, signal),
    [recordType],
    { enabled: Boolean(recordType) },
  );

  const fields = useMemo(
    () => (layout.data ? allFields(layout.data).filter((field) => !field.read_only) : []),
    [layout.data],
  );
  const byName = useMemo(
    () => new Map(fields.map((field) => [field.name, field])),
    [fields],
  );

  const [shared, setShared] = useState<string[]>([]);
  const [columns, setColumns] = useState<string[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [rows, setRows] = useState<string[][]>([]);

  // A new record type is a different tray: the old split names fields that
  // this form does not have, and the old rows are somebody else's data.
  useEffect(() => {
    if (!layout.data) return;
    const guess = firstGuess(layout.data, recordType);
    setShared(guess.shared);
    setColumns(guess.columns);
    setValues({});
    setRows(Array.from({ length: ROWS }, () => guess.columns.map(() => "")));
  }, [layout.data, recordType]);

  const setCell = (row: number, column: number, value: string) =>
    setRows((current) =>
      current.map((line, index) =>
        index === row ? line.map((old, spot) => (spot === column ? value : old)) : line,
      ),
    );

  /**
   * Pasting a block out of Excel.
   *
   * Half the reason people stay in a spreadsheet is that they already have one.
   * A paste starting at the focused cell fills down and across, growing the
   * tray if the block is taller than it — so the answer to "I already typed
   * this in Excel" is Ctrl+V rather than "then use the importer instead".
   */
  const paste = (row: number, column: number, text: string) => {
    const block = text
      .replace(/\r\n?/g, "\n")
      .replace(/\n$/, "")
      .split("\n")
      .map((line) => line.split("\t"));
    if (block.length === 1 && block[0]?.length === 1) return false;

    setRows((current) => {
      const next = current.map((line) => [...line]);
      while (next.length < row + block.length) next.push(columns.map(() => ""));
      block.forEach((line, down) =>
        line.forEach((value, across) => {
          const target = next[row + down];
          if (target && column + across < columns.length) {
            target[column + across] = value.trim();
          }
        }),
      );
      return next;
    });
    return true;
  };

  /** Rows with something in them. A tray of forty is typed into a grid of fifty. */
  const filled = rows.filter((row) => row.some((cellValue) => cellValue.trim() !== ""));

  const missingShared = shared.filter(
    (name) => byName.get(name)?.required && !(values[name] ?? "").trim(),
  );
  const missingColumns = fields
    .filter((field) => field.required)
    .filter((field) => !columns.includes(field.name) && !(values[field.name] ?? "").trim());

  const send = useAction(async () => {
    const chosen = columns.map((name) => byName.get(name)).filter((f): f is FormField => !!f);
    const headings = headingsFor(chosen);
    const csv = toCsv(
      headings,
      filled.map((row) => columns.map((_, index) => row[index] ?? "")),
    );

    const file = new File([csv], `tray-${new Date().toISOString().slice(0, 10)}.csv`, {
      type: "text/csv",
    });
    const batch = await api.upload<{ id: string }>("/imports", file, {
      record_type: recordType,
    });

    // The mapping is not a guess here — we wrote the headings ourselves, so we
    // know exactly what each one fills. Sending it explicitly means the check
    // screen opens with nothing left to decide.
    await api.patch(`/imports/${batch.id}`, {
      mapping: Object.fromEntries(headings.map((heading, index) => [heading, chosen[index]!.name])),
      defaults: Object.fromEntries(
        shared
          .map((name) => [name, (values[name] ?? "").trim()])
          .filter(([, value]) => value !== ""),
      ),
      note: `Typed as a tray of ${filled.length}`,
    });
    navigate(`/import/${batch.id}`);
  });

  if (!kind) {
    return (
      <Empty title="Not your job, happily">
        Registering a tray writes many records at once, so it needs supervisor access to the
        module it writes into. Ask whoever administers the platform.
      </Empty>
    );
  }
  if (layout.loading) return <Loading />;
  if (!layout.data) return <ErrorNote message={layout.error ?? "That form is not available."} />;

  const spare = fields.filter(
    (field) => !shared.includes(field.name) && !columns.includes(field.name),
  );

  return (
    <div className="tray-page">
      <PageHeader
        title="Register a tray"
        subtitle={
          "Everything the tray shares is set once. Everything that differs is a column you " +
          "type down. Nothing is written until you have checked it."
        }
      />

      {allowed.length > 1 && (
        // Wraps: six record types do not fit across a phone, and a row that
        // overflows takes the whole page sideways with it.
        <div className="row-tight" style={{ flexWrap: "wrap" }}>
          {allowed.map((item) => (
            <button
              key={item.value}
              type="button"
              className={`btn btn-sm ${item.value === recordType ? "btn-primary" : ""}`}
              onClick={() => setParams({ type: item.value })}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}

      {/* --------------------------------------------------- the same for all */}
      <section className="card">
        <div className="card-header">
          <h2 className="card-title">The same for every one</h2>
          <span className="muted small">Typed once, applied to every row.</span>
        </div>
        <div className="card-body">
          {shared.length === 0 ? (
            <p className="muted small">
              Nothing is shared yet. Move a field here from the list below and it stops being a
              column you have to type forty times.
            </p>
          ) : (
            <div className="form-grid">
              {shared.map((name) => {
                const field = byName.get(name);
                if (!field) return null;
                const options = field.value_list
                  ? (layout.data?.value_list_options[field.value_list] ?? [])
                  : [];
                return (
                  <div key={name} className="field" style={{ gridColumn: "span 4" }}>
                    <span className="shared-head">
                      <span className="field-label">
                        {field.label}
                        {field.required && <span className="required"> *</span>}
                      </span>
                      <button
                        type="button"
                        className="linkish"
                        onClick={() => {
                          setShared((current) => current.filter((item) => item !== name));
                          setValues((current) => ({ ...current, [name]: "" }));
                        }}
                      >
                        Not shared
                      </button>
                    </span>
                    {options.length > 0 ? (
                      <select
                        className="input"
                        aria-label={field.label}
                        value={values[name] ?? ""}
                        onChange={(event) =>
                          setValues((current) => ({ ...current, [name]: event.target.value }))
                        }
                      >
                        <option value="">Not set</option>
                        {/* The stored value, not the label. The importer
                            accepts either — its lookup tables key on both —
                            but the check screen's own site chooser reads an
                            identifier, and sending the label would leave it
                            looking unset on a tray that had set it. */}
                        {options.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        className="input"
                        aria-label={field.label}
                        type={field.kind === "date" ? "date" : "text"}
                        value={values[name] ?? ""}
                        placeholder={field.placeholder ?? ""}
                        onChange={(event) =>
                          setValues((current) => ({ ...current, [name]: event.target.value }))
                        }
                      />
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </section>

      {/* ------------------------------------------------------------ columns */}
      <section className="card">
        <div className="card-header">
          <h2 className="card-title">Different for each</h2>
          <span className="muted small">
            {columns.length} column{columns.length === 1 ? "" : "s"} · {filled.length} row
            {filled.length === 1 ? "" : "s"} with something in them
          </span>
        </div>
        <div className="card-body">
          <div className="chips">
            {columns.map((name) => (
              <span key={name} className="chip chip-removable">
                {byName.get(name)?.label ?? name}
                {byName.get(name)?.required && <span className="required"> *</span>}
                <button
                  type="button"
                  aria-label={`Remove the ${byName.get(name)?.label ?? name} column`}
                  onClick={() => {
                    const index = columns.indexOf(name);
                    setColumns((current) => current.filter((item) => item !== name));
                    setRows((current) =>
                      current.map((row) => row.filter((_, spot) => spot !== index)),
                    );
                  }}
                >
                  ×
                </button>
              </span>
            ))}
          </div>

          <div className="tray-scroll">
            <table className="tray">
              <thead>
                <tr>
                  <th className="tray-number" />
                  {columns.map((name) => (
                    <th key={name}>
                      {byName.get(name)?.label ?? name}
                      {byName.get(name)?.required && <span className="required"> *</span>}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, down) => (
                  <tr key={down}>
                    <td className="tray-number">{down + 1}</td>
                    {columns.map((name, across) => {
                      const field = byName.get(name);
                      const list = field?.value_list;
                      return (
                        <td key={name}>
                          <input
                            className="tray-cell"
                            type={field?.kind === "date" ? "date" : "text"}
                            list={list ? `tray-list-${list}` : undefined}
                            value={row[across] ?? ""}
                            aria-label={`${field?.label ?? name}, row ${down + 1}`}
                            onChange={(event) => setCell(down, across, event.target.value)}
                            onPaste={(event) => {
                              const text = event.clipboardData.getData("text/plain");
                              if (paste(down, across, text)) event.preventDefault();
                            }}
                            onKeyDown={(event) => {
                              if (event.key === "Enter" && down === rows.length - 1) {
                                setRows((current) => [...current, columns.map(() => "")]);
                              }
                            }}
                          />
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* One datalist per value list, shared by every cell in its column:
              typing is faster than choosing, and an unknown name is caught on
              the check screen rather than being impossible to type. */}
          {Object.entries(layout.data.value_list_options).map(([name, options]) => (
            <datalist key={name} id={`tray-list-${name}`}>
              {options.map((option) => (
                <option key={option.value} value={option.label} />
              ))}
            </datalist>
          ))}

          <div className="row-tight" style={{ marginTop: 12 }}>
            <button
              type="button"
              className="btn btn-sm"
              onClick={() =>
                setRows((current) => [
                  ...current,
                  ...Array.from({ length: ROWS }, () => columns.map(() => "")),
                ])
              }
            >
              {ROWS} more rows
            </button>
            <span className="muted small">
              Paste a block straight out of a spreadsheet and it fills down and across from the
              cell you paste into.
            </span>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------ unused fields */}
      {spare.length > 0 && (
        <details className="card">
          <summary className="card-header">
            <h2 className="card-title">Everything else on this form</h2>
            <span className="muted small">
              {spare.length} field{spare.length === 1 ? "" : "s"} not recorded for this tray. Add
              one as a shared value or as a column.
            </span>
          </summary>
          <div className="card-body">
            <div className="spare-grid">
              {spare.map((field) => (
                <div key={field.name} className="spare">
                  <span className="spare-label">
                    {field.label}
                    {field.required && <span className="required"> *</span>}
                  </span>
                  <span className="row-tight">
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => setShared((current) => [...current, field.name])}
                    >
                      Same for all
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => {
                        setColumns((current) => [...current, field.name]);
                        setRows((current) => current.map((row) => [...row, ""]));
                      }}
                    >
                      A column
                    </button>
                  </span>
                </div>
              ))}
            </div>
          </div>
        </details>
      )}

      {/* ------------------------------------------------------------- finish */}
      {send.error && <ErrorNote message={send.error} />}

      {(missingShared.length > 0 || missingColumns.length > 0) && (
        <div className="alert alert-warning">
          {[...missingShared, ...missingColumns.map((field) => field.name)]
            .map((name) => byName.get(name)?.label ?? name)
            .join(", ")}{" "}
          {missingShared.length + missingColumns.length === 1 ? "is" : "are"} required on every
          record. Set {missingShared.length + missingColumns.length === 1 ? "it" : "them"} above,
          or add {missingShared.length + missingColumns.length === 1 ? "it" : "them"} as a column.
        </div>
      )}

      <div className="row-tight">
        <button
          type="button"
          className="btn btn-primary"
          disabled={filled.length === 0 || send.running}
          onClick={() => void send.run()}
        >
          {send.running
            ? "Checking…"
            : `Check ${filled.length} row${filled.length === 1 ? "" : "s"}`}
        </button>
        <span className="muted small">
          Nothing is written yet. The next screen shows every row as the platform reads it, and
          what is wrong with the ones that are wrong.
        </span>
      </div>
    </div>
  );
}

export default BatchEntry;
