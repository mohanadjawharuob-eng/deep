/**
 * The record card: one record shown the way a cataloguer expects to see it.
 *
 * Nothing here knows what a museum object *is*. The backend serves a layout —
 * tabs, groups, fields, widths, help text, which value list fills which
 * dropdown — and this renders it. Add a field to `app/services/forms.py` and
 * it appears here, in the right tab, at the right width, with its dropdown
 * populated, without a line of frontend work.
 *
 * That indirection is the point. The layout is a curatorial decision and it
 * will change; it should change in one place.
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import {
  api,
  type FormField,
  type FormLayout,
  type FormPortal,
  type Page,
} from "../lib/api";
import { useDebounced, useQuery } from "../lib/hooks";
import { formatDate, formatDateTime, humanise } from "./ui";

export type RecordValues = Record<string, unknown>;

/* --------------------------------------------------------------------------
 * Where a field's value lives
 *
 * A field the platform ships has a column: `values.height_mm`. A field an
 * institution added has no column — adding one would mean a migration every
 * time somebody invents a field — so its value sits inside the record's
 * `metadata_json` under the field's own name.
 *
 * Everything that reads or writes a value goes through these two, so the
 * difference is stated once here rather than remembered in six screens.
 * ----------------------------------------------------------------------- */

/** The value of one field, whichever of the two places it lives in. */
export function fieldValue(values: RecordValues, field: FormField): unknown {
  if (!field.custom) return values[field.name];
  const bag = values.metadata_json;
  return bag && typeof bag === "object" ? (bag as RecordValues)[field.name] : undefined;
}

/**
 * One field's new value, as a patch body.
 *
 * For a custom field that is the *whole* bag with one key changed, not the one
 * key — `metadata_json` is a single column, and sending it with one key in it
 * would erase every other custom field on the record.
 */
export function fieldPatch(values: RecordValues, field: FormField, next: unknown): RecordValues {
  if (!field.custom) return { [field.name]: next };
  const current = values.metadata_json;
  const bag: RecordValues =
    current && typeof current === "object" ? { ...(current as RecordValues) } : {};
  if (next === null || next === undefined || next === "") delete bag[field.name];
  else bag[field.name] = next;
  return { metadata_json: bag };
}

/* --------------------------------------------------------------------------
 * Reading a value
 * ----------------------------------------------------------------------- */

/** Where a reference field's target lives, for both search and linking. */
const REFERENCES: Record<string, { endpoint: string; label: string; to: (id: string) => string }> = {
  collection: {
    endpoint: "/museum/collections",
    label: "name",
    to: (id) => `/museum/collections/${id}`,
  },
  storage_location: {
    endpoint: "/storage/locations",
    label: "display_path",
    to: (id) => `/storage?location=${id}`,
  },
  artifact: { endpoint: "/artifacts", label: "name", to: (id) => `/artifacts/${id}` },
  site: { endpoint: "/sites", label: "name", to: (id) => `/sites/${id}` },
};

/** Fields whose value is an identifier rather than prose. */
const IDENTIFIER_FIELDS = new Set([
  "accession_number",
  "former_number",
  "inventory_number",
  "code",
  "catalogue_number",
  "field_number",
]);

function optionLabel(layout: FormLayout, field: FormField, value: unknown): string | null {
  if (!field.value_list) return null;
  const options = layout.value_list_options[field.value_list];
  const match = options?.find((option) => option.value === String(value));
  return match?.label ?? null;
}

/** How a value reads when nobody is editing it. */
function ReadValue({
  layout,
  field,
  value,
}: {
  layout: FormLayout;
  field: FormField;
  value: unknown;
}) {
  if (value === null || value === undefined || value === "") {
    return <span className="value-empty">—</span>;
  }

  switch (field.kind) {
    case "boolean":
      return <>{value ? "Yes" : "No"}</>;

    case "date":
      return <>{formatDate(String(value))}</>;

    case "datetime":
      return <>{formatDateTime(String(value))}</>;

    case "number":
    case "integer": {
      const numeric = Number(value);
      const shown = Number.isFinite(numeric) ? numeric.toLocaleString() : String(value);
      return (
        <>
          {shown}
          {field.unit ? <span className="unit"> {field.unit}</span> : null}
        </>
      );
    }

    case "select":
      return <>{optionLabel(layout, field, value) ?? humanise(String(value))}</>;

    case "multiselect":
    case "tags": {
      const items = Array.isArray(value) ? value : [value];
      if (items.length === 0) return <span className="value-empty">—</span>;
      return (
        <span className="chips">
          {items.map((item) => (
            <span key={String(item)} className="chip">
              {optionLabel(layout, field, item) ?? String(item)}
            </span>
          ))}
        </span>
      );
    }

    case "reference": {
      const target = field.references ? REFERENCES[field.references] : undefined;
      const label = optionLabel(layout, field, value);
      if (!target) return <>{label ?? String(value)}</>;
      return (
        <Link to={target.to(String(value))}>
          {label ?? <ReferenceLabel reference={field.references!} id={String(value)} />}
        </Link>
      );
    }

    case "json": {
      // Braces and quotation marks are a programmer's view of what is, to
      // everybody else, a short list of things somebody wrote down. Shown as
      // that list where it can be, and as raw JSON only where it genuinely is
      // nested and no list would be honest.
      const entries =
        value && typeof value === "object" && !Array.isArray(value)
          ? Object.entries(value as Record<string, unknown>)
          : null;
      if (!entries) return <pre className="json">{JSON.stringify(value, null, 2)}</pre>;
      if (entries.length === 0) return <span className="value-empty">—</span>;
      return (
        <dl className="extra-fields">
          {entries.map(([key, item]) => (
            <div key={key}>
              <dt>{humanise(key)}</dt>
              <dd>
                {item !== null && typeof item === "object"
                  ? JSON.stringify(item)
                  : typeof item === "boolean"
                    ? item
                      ? "Yes"
                      : "No"
                    : String(item)}
              </dd>
            </div>
          ))}
        </dl>
      );
    }

    case "textarea":
      return <span className="prose">{String(value)}</span>;

    default:
      // An identifier is monospace wherever it appears: the whole point of
      // the number is that it can be compared, character by character,
      // against the one written on the object.
      return IDENTIFIER_FIELDS.has(field.name) ? (
        <span className="mono">{String(value)}</span>
      ) : (
        <>{String(value)}</>
      );
  }
}

/**
 * A reference with no value list behind it — resolve the one record so the
 * card shows a name rather than a UUID nobody can read.
 */
function ReferenceLabel({ reference, id }: { reference: string; id: string }) {
  const target = REFERENCES[reference];
  const state = useQuery<Record<string, unknown>>(
    (signal) => api.get(`${target!.endpoint}/${id}`, undefined, signal),
    [reference, id],
    { enabled: Boolean(target) },
  );
  if (!target) return <span className="mono small">{id}</span>;
  if (state.loading) return <span className="muted small">…</span>;
  const value = state.data?.[target.label] ?? state.data?.name;
  return <>{value ? String(value) : id}</>;
}

/* --------------------------------------------------------------------------
 * Editing a value
 * ----------------------------------------------------------------------- */
function EditValue({
  layout,
  field,
  value,
  onChange,
}: {
  layout: FormLayout;
  field: FormField;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const options = field.value_list ? (layout.value_list_options[field.value_list] ?? []) : [];
  const text = value === null || value === undefined ? "" : String(value);

  if (field.read_only) {
    return (
      <div className="input input-static">
        <ReadValue layout={layout} field={field} value={value} />
      </div>
    );
  }

  switch (field.kind) {
    case "textarea":
      return (
        <textarea
          className="input"
          rows={4}
          value={text}
          placeholder={field.placeholder ?? ""}
          maxLength={field.max_length ?? undefined}
          onChange={(event) => onChange(event.target.value || null)}
        />
      );

    case "boolean":
      return (
        <label className="switch">
          <input
            type="checkbox"
            checked={Boolean(value)}
            onChange={(event) => onChange(event.target.checked)}
          />
          <span>{value ? "Yes" : "No"}</span>
        </label>
      );

    case "date":
      return (
        <input
          className="input"
          type="date"
          value={text.slice(0, 10)}
          onChange={(event) => onChange(event.target.value || null)}
        />
      );

    case "datetime":
      return (
        <input
          className="input"
          type="datetime-local"
          value={text.slice(0, 16)}
          onChange={(event) => onChange(event.target.value || null)}
        />
      );

    case "number":
    case "integer":
      return (
        <div className="input-affix">
          <input
            className="input"
            type="number"
            step={field.kind === "integer" ? 1 : "any"}
            value={text}
            placeholder={field.placeholder ?? ""}
            onChange={(event) =>
              onChange(event.target.value === "" ? null : Number(event.target.value))
            }
          />
          {field.unit && <span className="affix">{field.unit}</span>}
        </div>
      );

    case "select":
      return (
        <select
          className="input"
          value={text}
          onChange={(event) => onChange(event.target.value || null)}
        >
          <option value="">—</option>
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      );

    case "multiselect":
    case "tags":
      return (
        <TagsInput
          value={Array.isArray(value) ? value.map(String) : []}
          suggestions={options.map((option) => option.label)}
          onChange={(next) => onChange(next.length ? next : null)}
        />
      );

    case "reference":
      if (options.length > 0) {
        return (
          <select
            className="input"
            value={text}
            onChange={(event) => onChange(event.target.value || null)}
          >
            <option value="">—</option>
            {options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        );
      }
      return (
        <ReferenceInput
          reference={field.references ?? ""}
          value={text || null}
          onChange={onChange}
        />
      );

    case "json":
      return (
        <textarea
          className="input mono"
          rows={4}
          value={typeof value === "string" ? value : JSON.stringify(value ?? {}, null, 2)}
          onChange={(event) => onChange(event.target.value)}
        />
      );

    default:
      return (
        <input
          className={`input ${IDENTIFIER_FIELDS.has(field.name) ? "mono" : ""}`}
          value={text}
          placeholder={field.placeholder ?? ""}
          maxLength={field.max_length ?? undefined}
          onChange={(event) => onChange(event.target.value || null)}
        />
      );
  }
}

/** Free-text tags: materials and techniques are lists nobody can enumerate. */
function TagsInput({
  value,
  suggestions,
  onChange,
}: {
  value: string[];
  suggestions: string[];
  onChange: (value: string[]) => void;
}) {
  const [draft, setDraft] = useState("");
  const listId = useRef(`tags-${Math.random().toString(36).slice(2)}`).current;

  const add = (raw: string) => {
    const item = raw.trim();
    if (!item || value.includes(item)) return;
    onChange([...value, item]);
    setDraft("");
  };

  return (
    <div className="tags-input">
      <div className="chips">
        {value.map((item) => (
          <span key={item} className="chip chip-removable">
            {item}
            <button
              type="button"
              aria-label={`Remove ${item}`}
              onClick={() => onChange(value.filter((other) => other !== item))}
            >
              ×
            </button>
          </span>
        ))}
      </div>
      <input
        className="input"
        list={listId}
        value={draft}
        placeholder="Type and press Enter"
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => add(draft)}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === ",") {
            event.preventDefault();
            add(draft);
          } else if (event.key === "Backspace" && !draft && value.length) {
            onChange(value.slice(0, -1));
          }
        }}
      />
      <datalist id={listId}>
        {suggestions.map((item) => (
          <option key={item} value={item} />
        ))}
      </datalist>
    </div>
  );
}

/** A reference too numerous for a dropdown: search it instead. */
function ReferenceInput({
  reference,
  value,
  onChange,
}: {
  reference: string;
  value: string | null;
  onChange: (value: string | null) => void;
}) {
  const target = REFERENCES[reference];
  const [term, setTerm] = useState("");
  const [open, setOpen] = useState(false);
  const debounced = useDebounced(term);

  const results = useQuery<Page<Record<string, unknown>>>(
    (signal) => api.get(target!.endpoint, { q: debounced, limit: 10 }, signal),
    [debounced],
    { enabled: Boolean(target) && open && debounced.length > 1 },
  );

  if (!target) return <input className="input" value={value ?? ""} readOnly />;

  if (value && !open) {
    return (
      <div className="input input-static row-tight">
        <span className="truncate">
          <ReferenceLabel reference={reference} id={value} />
        </span>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => onChange(null)}>
          Clear
        </button>
      </div>
    );
  }

  return (
    <div className="lookup">
      <input
        className="input"
        value={term}
        placeholder="Search…"
        onFocus={() => setOpen(true)}
        onChange={(event) => setTerm(event.target.value)}
      />
      {open && debounced.length > 1 && (
        <div className="lookup-menu">
          {results.loading && <div className="lookup-note">Searching…</div>}
          {!results.loading && results.data?.items.length === 0 && (
            <div className="lookup-note">Nothing matched.</div>
          )}
          {results.data?.items.map((item) => (
            <button
              key={String(item.id)}
              type="button"
              className="lookup-item"
              onClick={() => {
                onChange(String(item.id));
                setOpen(false);
                setTerm("");
              }}
            >
              {String(item[target.label] ?? item.name ?? item.id)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* --------------------------------------------------------------------------
 * The card
 * ----------------------------------------------------------------------- */
function isEmpty(value: unknown) {
  return value === null || value === undefined || value === "" ||
    (Array.isArray(value) && value.length === 0);
}

export function FieldCell({
  layout,
  field,
  values,
  editing,
  onChange,
}: {
  layout: FormLayout;
  field: FormField;
  values: RecordValues;
  editing: boolean;
  onChange: (name: string, value: unknown) => void;
}) {
  const value = fieldValue(values, field);
  return (
    <div className="form-cell" style={{ gridColumn: `span ${field.width}` }}>
      <div className="form-label">
        {field.label}
        {field.required && editing && <span className="required">*</span>}
      </div>
      {editing ? (
        <div className={field.required && isEmpty(value) ? "cell-invalid" : undefined}>
          <EditValue
            layout={layout}
            field={field}
            value={value}
            onChange={(next) => {
              // A custom field's edit is a change to `metadata_json`, so the
              // draft carries the whole bag. Callers stay unaware of the
              // difference: they set one key, save one key, and the record
              // keeps every other custom field it had.
              for (const [key, patched] of Object.entries(fieldPatch(values, field, next))) {
                onChange(key, patched);
              }
            }}
          />
        </div>
      ) : (
        <div className="form-value">
          <ReadValue layout={layout} field={field} value={value} />
        </div>
      )}
      {editing && field.required && isEmpty(value) && (
        <div className="form-required-hint">Required before publication</div>
      )}
      {field.help && editing && <div className="form-help">{field.help}</div>}
    </div>
  );
}

/** Related records shown inline — FileMaker calls this a portal. */
function Portal({ portal, recordId }: { portal: FormPortal; recordId: string }) {
  const url = portal.endpoint.replace("/api/v1", "").replace("{id}", recordId);
  const state = useQuery<Page<Record<string, unknown>> | Record<string, unknown>[]>(
    (signal) => api.get(url, undefined, signal),
    [url],
    { enabled: Boolean(recordId) },
  );

  const rows = Array.isArray(state.data) ? state.data : (state.data?.items ?? []);

  return (
    <section className="card portal">
      <div className="card-header">
        <span className="card-title">{portal.label}</span>
        <span className="small muted">{rows.length || ""}</span>
      </div>
      {state.loading ? (
        <div className="card-body small muted">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="card-body small muted">Nothing recorded.</div>
      ) : (
        <div className="table-wrap">
          <table className="table table-dense">
            <thead>
              <tr>
                {portal.columns.map((column) => (
                  <th key={column}>{humanise(column)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={String(row.id ?? index)}>
                  {portal.columns.map((column) => (
                    <td key={column}>{portalCell(column, row[column])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function portalCell(column: string, value: unknown): ReactNode {
  if (value === null || value === undefined || value === "") return <span className="muted">—</span>;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  const text = String(value);
  if (/_(at|on)$/.test(column)) return formatDate(text) ?? text;
  if (/^(status|type|kind|reason|treatment_type)$/.test(column)) return humanise(text);
  return text;
}

/**
 * The tab strip, rendered separately from the card.
 *
 * It lives in the record's sticky header, not above the fields: forty fields
 * down, a cataloguer still needs to be able to change tab without scrolling
 * back. That is the whole reason the tab state is the caller's.
 */
export function RecordTabs({
  layout,
  tab,
  onTab,
}: {
  layout: FormLayout;
  tab: string;
  onTab: (key: string) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {layout.tabs.map((item) => (
        <button
          key={item.key}
          type="button"
          role="tab"
          aria-selected={item.key === tab}
          className={`tab ${item.key === tab ? "active" : ""}`}
          onClick={() => onTab(item.key)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

/** The first tab of a layout, for a caller initialising its own tab state. */
export function firstTab(layout: FormLayout | undefined) {
  return layout?.tabs[0]?.key ?? "";
}

/**
 * The card itself: the fields of the active tab, then the portals.
 *
 * `editing` and `tab` are both the caller's, because create and edit are the
 * same card with different destinations, and because the tab strip is drawn
 * in the sticky header above.
 */
export function RecordCard({
  layout,
  values,
  editing,
  onChange,
  recordId,
  hidePortals,
  tab: controlledTab,
}: {
  layout: FormLayout;
  values: RecordValues;
  editing: boolean;
  onChange: (name: string, value: unknown) => void;
  recordId?: string;
  hidePortals?: boolean;
  /** Omit to let the card own its own tab state. */
  tab?: string;
}) {
  const [ownTab, setOwnTab] = useState(layout.tabs[0]?.key ?? "");
  const tab = controlledTab ?? ownTab;

  useEffect(() => {
    if (controlledTab === undefined && !layout.tabs.some((item) => item.key === ownTab)) {
      setOwnTab(layout.tabs[0]?.key ?? "");
    }
  }, [layout, ownTab, controlledTab]);

  const active = useMemo(
    () => layout.tabs.find((item) => item.key === tab) ?? layout.tabs[0],
    [layout, tab],
  );

  return (
    <>
      {controlledTab === undefined && (
        <RecordTabs layout={layout} tab={tab} onTab={setOwnTab} />
      )}

      <div className="record">
        {active?.groups.map((group) => (
          <section key={group.label} className="card">
            <div className="form-group-head">
              <div className="form-group-title">{group.label}</div>
              {group.help && <p className="form-group-help">{group.help}</p>}
            </div>
            <div style={{ padding: "14px 16px" }}>
              <div className="form-grid">
                {group.fields.map((field) => (
                  <FieldCell
                    key={field.name}
                    layout={layout}
                    field={field}
                    values={values}
                    editing={editing}
                    onChange={onChange}
                  />
                ))}
              </div>
            </div>
          </section>
        ))}

        {!hidePortals &&
          recordId &&
          !editing &&
          layout.portals.map((portal) => (
            <Portal key={portal.key} portal={portal} recordId={recordId} />
          ))}
      </div>
    </>
  );
}

/** Which fields a layout has, flattened — used to build a create payload. */
export function layoutFields(layout: FormLayout): FormField[] {
  return layout.tabs.flatMap((tab) => tab.groups.flatMap((group) => group.fields));
}

/**
 * The keys a create or edit payload may carry.
 *
 * The layout's own field names, plus `metadata_json` — which is not a field on
 * every layout but is where the institution's own fields are stored, so a form
 * that filtered strictly by field name would drop every custom value on its
 * way to the API and say nothing about it.
 */
export function writableKeys(layout: FormLayout): Set<string> {
  const keys = new Set(layoutFields(layout).map((field) => field.name));
  keys.add("metadata_json");
  return keys;
}
