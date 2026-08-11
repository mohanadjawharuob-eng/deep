/**
 * Adding your own fields to the platform's forms.
 *
 * Every institution records something the next one does not — a ministry file
 * number, a Munsell reading nobody else takes, the name of the person who
 * reported the site. Until this screen existed the answer was a spreadsheet
 * kept beside the platform, which is where the real recording then quietly
 * happens, and it is not backed up, not permissioned and not exported.
 *
 * A field added here appears at once on the record card, in the edit form, in
 * the spreadsheet importer's column list and in the register, because all four
 * are drawn from one description of the form. Nothing has to be told twice.
 *
 * Two things this screen is careful to say out loud, because both are
 * irreversible in the way that matters:
 *
 * **The label can change; the field cannot move.** Its storage name is fixed
 * at creation, so renaming the caption is free and safe, and there is no
 * button that would silently orphan a year of values.
 *
 * **Removing a field is retiring it.** The form stops offering it, and every
 * value already recorded stays on its record and in every export. Actually
 * erasing the values is a second, separate, spelt-out choice.
 */

import { useState } from "react";

import { api } from "../lib/api";
import { useAction, useQuery, useSession } from "../lib/hooks";
import { Empty, ErrorNote, Loading, PageHeader } from "../components/ui";

type CustomField = {
  id: string;
  record_type: string;
  name: string;
  label: string;
  kind: string;
  choices?: string[] | null;
  help?: string | null;
  required: boolean;
  position: number;
  is_active: boolean;
};

/** The forms a field can be added to, named as somebody would say them. */
const FORMS: { key: string; label: string; where: string }[] = [
  { key: "site", label: "Sites", where: "Excavations → a site" },
  { key: "excavation_context", label: "Contexts", where: "Excavations → a context" },
  { key: "artifact", label: "Finds", where: "Excavations → a find" },
  { key: "museum_object", label: "Museum objects", where: "Museum → an object" },
  { key: "equipment", label: "Equipment", where: "Store → equipment" },
  { key: "consumable", label: "Stock", where: "Store → stock" },
];

/** What a field can be, described by what somebody types into it. */
const KINDS: { key: string; label: string; note: string }[] = [
  { key: "text", label: "Short text", note: "One line. A number, a name, a reference." },
  { key: "textarea", label: "Long text", note: "A paragraph or several." },
  { key: "select", label: "Dropdown", note: "One of a list you write below." },
  { key: "number", label: "Number", note: "Decimals allowed." },
  { key: "integer", label: "Whole number", note: "No decimals." },
  { key: "date", label: "Date", note: "A calendar." },
  { key: "boolean", label: "Yes / no", note: "A switch." },
];

function kindLabel(kind: string) {
  return KINDS.find((item) => item.key === kind)?.label ?? kind;
}

export function CustomFieldsAdmin() {
  const { user, levelIn } = useSession();
  const isAdmin = levelIn("archaeology") === "administrator" && user?.role === "admin";

  const [form, setForm] = useState("site");
  const [adding, setAdding] = useState(false);

  const fields = useQuery<CustomField[]>(
    (signal) =>
      api.get("/custom-fields", { record_type: form, include_retired: true }, signal),
    [form],
  );

  if (!isAdmin) {
    return (
      <Empty title="Not your job, happily">
        What the institution records is an administrator's decision — everybody
        fills the same form in, and a form that changes under people is worse
        than one that is missing a field.
      </Empty>
    );
  }

  const chosen = FORMS.find((item) => item.key === form) ?? FORMS[0]!;
  const rows = fields.data ?? [];
  const live = rows.filter((row) => row.is_active);
  const retired = rows.filter((row) => !row.is_active);

  return (
    <>
      <PageHeader
        title="Our own fields"
        subtitle="Fields this institution has added to the platform's forms"
        actions={
          <button type="button" className="btn btn-primary btn-sm" onClick={() => setAdding(true)}>
            Add a field
          </button>
        }
      />

      <section className="card">
        <div className="card-body">
          <label className="field" style={{ maxWidth: 380 }}>
            <span className="field-label">Which form</span>
            <select className="input" value={form} onChange={(event) => setForm(event.target.value)}>
              {FORMS.map((item) => (
                <option key={item.key} value={item.key}>
                  {item.label}
                </option>
              ))}
            </select>
            <span className="field-help">
              Fields added here appear on {chosen.where}, on the tab called “Our own
              fields” — and in the importer and the register at the same time.
            </span>
          </label>
        </div>
      </section>

      {adding && (
        <NewField
          recordType={form}
          formLabel={chosen.label}
          taken={rows.map((row) => row.name)}
          onClose={() => setAdding(false)}
          onMade={() => {
            setAdding(false);
            fields.reload();
          }}
        />
      )}

      {fields.loading ? (
        <Loading rows={4} />
      ) : fields.error ? (
        <ErrorNote message={fields.error} onRetry={fields.reload} />
      ) : rows.length === 0 ? (
        <Empty title={`No fields of your own on ${chosen.label.toLowerCase()} yet`}>
          The form has what the platform ships with. Add a field for anything this
          institution records that it does not.
        </Empty>
      ) : (
        <>
          <section className="card" style={{ marginTop: 16 }}>
            <div className="card-header">
              <span className="card-title">On the form</span>
              <span className="muted small">{live.length}</span>
            </div>
            <div className="card-body">
              {live.length === 0 ? (
                <p className="muted small" style={{ margin: 0 }}>
                  Every field on this form has been retired.
                </p>
              ) : (
                live.map((field) => (
                  <FieldRow key={field.id} field={field} onChanged={() => fields.reload()} />
                ))
              )}
            </div>
          </section>

          {retired.length > 0 && (
            <section className="card" style={{ marginTop: 16 }}>
              <div className="card-header">
                <span className="card-title">Retired</span>
                <span className="muted small">{retired.length}</span>
              </div>
              <div className="card-body">
                <p className="muted small" style={{ marginTop: 0 }}>
                  Off the form. Every value already recorded is still on its record and
                  in every export — these are here so that nothing recorded under them
                  is a mystery later.
                </p>
                {retired.map((field) => (
                  <FieldRow key={field.id} field={field} onChanged={() => fields.reload()} />
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </>
  );
}

/* -------------------------------------------------------------------------- */

function FieldRow({ field, onChanged }: { field: CustomField; onChanged: () => void }) {
  const [editing, setEditing] = useState(false);
  const [removing, setRemoving] = useState(false);

  const restore = useAction(async () => {
    await api.patch(`/custom-fields/${field.id}`, { is_active: true });
    onChanged();
  });

  return (
    <div className="inset-form" style={{ marginBottom: 10 }}>
      <div className="row-tight" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
        <div>
          <span className="strong">{field.label}</span>{" "}
          <span className="muted small">
            {kindLabel(field.kind)}
            {field.required ? " · must be filled in" : ""}
          </span>
          <div className="muted small">
            {/* The storage name matters to exactly one person: whoever maps a
                spreadsheet column onto it. Shown, quietly, never offered as
                something to change. */}
            stored as <span className="mono">{field.name}</span>
            {field.choices?.length ? ` · ${field.choices.join(", ")}` : ""}
          </div>
          {field.help && <div className="muted small">{field.help}</div>}
        </div>

        <div className="row-tight">
          {field.is_active ? (
            <>
              <button type="button" className="btn btn-sm" onClick={() => setEditing(!editing)}>
                {editing ? "Done" : "Change"}
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setRemoving(true)}
              >
                Remove
              </button>
            </>
          ) : (
            <button
              type="button"
              className="btn btn-sm"
              disabled={restore.running}
              onClick={() => void restore.run()}
            >
              {restore.running ? "Putting back…" : "Put back on the form"}
            </button>
          )}
        </div>
      </div>

      {restore.error && <ErrorNote message={restore.error} />}
      {editing && (
        <EditField
          field={field}
          onSaved={() => {
            setEditing(false);
            onChanged();
          }}
        />
      )}
      {removing && (
        <RemoveField
          field={field}
          onClose={() => setRemoving(false)}
          onDone={() => {
            setRemoving(false);
            onChanged();
          }}
        />
      )}
    </div>
  );
}

function EditField({ field, onSaved }: { field: CustomField; onSaved: () => void }) {
  const [label, setLabel] = useState(field.label);
  const [help, setHelp] = useState(field.help ?? "");
  const [kind, setKind] = useState(field.kind);
  const [choices, setChoices] = useState((field.choices ?? []).join("\n"));
  const [required, setRequired] = useState(field.required);
  const [position, setPosition] = useState(String(field.position));

  const save = useAction(async () => {
    await api.patch(`/custom-fields/${field.id}`, {
      label: label.trim(),
      help: help.trim() || null,
      kind,
      choices: kind === "select" ? splitChoices(choices) : null,
      required,
      position: Number(position) || 0,
    });
    onSaved();
  });

  return (
    <div style={{ marginTop: 10 }}>
      <Shape
        label={label}
        setLabel={setLabel}
        kind={kind}
        setKind={setKind}
        choices={choices}
        setChoices={setChoices}
        help={help}
        setHelp={setHelp}
        required={required}
        setRequired={setRequired}
        position={position}
        setPosition={setPosition}
      />
      {save.error && <ErrorNote message={save.error} />}
      <div className="row-tight" style={{ marginTop: 8 }}>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          disabled={!label.trim() || save.running}
          onClick={() => void save.run()}
        >
          {save.running ? "Saving…" : "Save"}
        </button>
      </div>
    </div>
  );
}

function RemoveField({
  field,
  onClose,
  onDone,
}: {
  field: CustomField;
  onClose: () => void;
  onDone: () => void;
}) {
  const [erase, setErase] = useState(false);
  const [typed, setTyped] = useState("");
  const [outcome, setOutcome] = useState<string | null>(null);

  const remove = useAction(async () => {
    const reply = await api.delete<{ detail: string }>(
      `/custom-fields/${field.id}${erase ? "?erase_values=true" : ""}`,
    );
    setOutcome(reply.detail);
    onDone();
  });

  if (outcome) return <div className="alert alert-info small">{outcome}</div>;

  return (
    <div className="alert alert-warning" style={{ marginTop: 10 }}>
      <b>Remove “{field.label}”?</b>
      <p className="small" style={{ marginBottom: 6 }}>
        It comes off the form. Everything already recorded under it stays on its
        record and in every export — nothing is lost, and you can put it back.
      </p>

      <label className="checkbox small">
        <input
          type="checkbox"
          checked={erase}
          onChange={(event) => {
            setErase(event.target.checked);
            setTyped("");
          }}
        />
        …and erase what was recorded under it, from every record. This cannot be
        undone.
      </label>

      {erase && (
        <label className="field" style={{ maxWidth: 320, marginTop: 8 }}>
          <span className="field-label">
            Type <span className="mono">erase</span> to confirm
          </span>
          <input
            className="input"
            value={typed}
            autoFocus
            onChange={(event) => setTyped(event.target.value)}
          />
        </label>
      )}

      {remove.error && <ErrorNote message={remove.error} />}

      <div className="row-tight" style={{ marginTop: 8 }}>
        <button
          type="button"
          className={`btn btn-sm ${erase ? "btn-danger-solid" : "btn-primary"}`}
          disabled={remove.running || (erase && typed.trim().toLowerCase() !== "erase")}
          onClick={() => void remove.run()}
        >
          {remove.running ? "Removing…" : erase ? "Remove and erase" : "Take it off the form"}
        </button>
        <button type="button" className="btn btn-sm" onClick={onClose}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function NewField({
  recordType,
  formLabel,
  taken,
  onClose,
  onMade,
}: {
  recordType: string;
  formLabel: string;
  taken: string[];
  onClose: () => void;
  onMade: () => void;
}) {
  const [label, setLabel] = useState("");
  const [kind, setKind] = useState("text");
  const [choices, setChoices] = useState("");
  const [help, setHelp] = useState("");
  const [required, setRequired] = useState(false);
  const [position, setPosition] = useState("0");

  const save = useAction(async () => {
    await api.post("/custom-fields", {
      record_type: recordType,
      label: label.trim(),
      kind,
      choices: kind === "select" ? splitChoices(choices) : null,
      help: help.trim() || null,
      required,
      position: Number(position) || 0,
    });
    onMade();
  });

  const clash = taken.includes(slugOf(label));

  return (
    <section className="card" style={{ marginTop: 16 }}>
      <div className="card-header">
        <span className="card-title">A new field on {formLabel.toLowerCase()}</span>
      </div>
      <div className="card-body">
        <Shape
          label={label}
          setLabel={setLabel}
          kind={kind}
          setKind={setKind}
          choices={choices}
          setChoices={setChoices}
          help={help}
          setHelp={setHelp}
          required={required}
          setRequired={setRequired}
          position={position}
          setPosition={setPosition}
        />

        {label.trim() && (
          <p className="muted small">
            It will be stored as <span className="mono">{slugOf(label)}</span> — that is
            the name a spreadsheet column maps onto, and it does not change afterwards.
          </p>
        )}
        {clash && (
          <div className="alert alert-warning small">
            There is already a field stored under that name on this form. Give this one a
            different label.
          </div>
        )}

        {save.error && <ErrorNote message={save.error} />}

        <div className="row-tight" style={{ marginTop: 8 }}>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={!label.trim() || clash || save.running}
            onClick={() => void save.run()}
          >
            {save.running ? "Adding…" : "Add it to the form"}
          </button>
          <button type="button" className="btn btn-sm" onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </section>
  );
}

/** The shape of a field, shared by adding one and changing one. */
function Shape({
  label,
  setLabel,
  kind,
  setKind,
  choices,
  setChoices,
  help,
  setHelp,
  required,
  setRequired,
  position,
  setPosition,
}: {
  label: string;
  setLabel: (value: string) => void;
  kind: string;
  setKind: (value: string) => void;
  choices: string;
  setChoices: (value: string) => void;
  help: string;
  setHelp: (value: string) => void;
  required: boolean;
  setRequired: (value: boolean) => void;
  position: string;
  setPosition: (value: string) => void;
}) {
  const note = KINDS.find((item) => item.key === kind)?.note;

  return (
    <div className="form-grid">
      <label className="field form-cell" style={{ gridColumn: "span 6" }}>
        <span className="field-label">What is it called?</span>
        <input
          className="input"
          value={label}
          autoFocus
          placeholder="Ministry file no."
          onChange={(event) => setLabel(event.target.value)}
        />
        <span className="field-help">The caption people read. Change it whenever you like.</span>
      </label>

      <label className="field form-cell" style={{ gridColumn: "span 6" }}>
        <span className="field-label">What goes in it?</span>
        <select className="input" value={kind} onChange={(event) => setKind(event.target.value)}>
          {KINDS.map((item) => (
            <option key={item.key} value={item.key}>
              {item.label}
            </option>
          ))}
        </select>
        {note && <span className="field-help">{note}</span>}
      </label>

      {kind === "select" && (
        <label className="field form-cell" style={{ gridColumn: "span 12" }}>
          <span className="field-label">The choices</span>
          <textarea
            className="input"
            rows={4}
            value={choices}
            placeholder={"Very good\nGood\nFair\nPoor"}
            onChange={(event) => setChoices(event.target.value)}
          />
          <span className="field-help">One per line, in the order they should appear.</span>
        </label>
      )}

      <label className="field form-cell" style={{ gridColumn: "span 12" }}>
        <span className="field-label">Note under the field (optional)</span>
        <input
          className="input"
          value={help}
          placeholder="As it appears on the ministry's own paperwork."
          onChange={(event) => setHelp(event.target.value)}
        />
      </label>

      <label className="field form-cell" style={{ gridColumn: "span 4" }}>
        <span className="field-label">Order</span>
        <input
          className="input"
          type="number"
          value={position}
          onChange={(event) => setPosition(event.target.value)}
        />
        <span className="field-help">Lower comes first.</span>
      </label>

      <div className="form-cell" style={{ gridColumn: "span 8" }}>
        <label className="checkbox small" style={{ marginTop: 22 }}>
          <input
            type="checkbox"
            checked={required}
            onChange={(event) => setRequired(event.target.checked)}
          />
          Mark it as needing to be filled in
        </label>
        {/* Said plainly, because the alternative is somebody adding a required
            field to a form of four thousand existing records and expecting the
            platform to have refused. */}
        <div className="muted small">
          The form marks it, and nothing that is already recorded is rejected for
          missing it.
        </div>
      </div>
    </div>
  );
}

function splitChoices(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

/** The same rule the API applies, so the preview is not a guess. */
function slugOf(label: string): string {
  return (
    label
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .slice(0, 60) || "field"
  );
}

export default CustomFieldsAdmin;
