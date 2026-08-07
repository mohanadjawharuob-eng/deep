/**
 * Editing a record, driven by the layout the platform already describes.
 *
 * The museum's record card has been editable since the module was built. Sites,
 * contexts and finds were read-only in the interface and writable only through
 * the API — so correcting a typed site code meant asking a developer, which for
 * an institution means it does not get corrected.
 *
 * The fix costs almost nothing, because the layouts written for the spreadsheet
 * importer describe exactly what an edit form needs: which fields exist, what
 * each one is called, what type it is, which are required, which the platform
 * sets rather than a person. One description, two uses, and they cannot drift
 * apart — a field added for the importer appears here on the same deployment.
 *
 * Two rules the museum card established and this keeps:
 *
 * **Nothing saves until you say so.** Edits collect in a draft; the count of
 * unsaved changes is on screen. Autosaving a form of fifty fields is how a
 * stray keystroke becomes a correction nobody made.
 *
 * **Only what changed is sent.** A PATCH of the whole record would overwrite a
 * field a colleague edited in the two minutes this form was open, and neither
 * of you would ever know.
 */

import { useMemo, useState } from "react";

import { api, type FormLayout } from "../lib/api";
import { useAction } from "../lib/hooks";
import { RecordCard, type RecordValues } from "./RecordCard";
import { ErrorNote } from "./ui";

export function useRecordEditor({
  layout,
  path,
  locked,
  onSaved,
}: {
  layout: FormLayout | undefined;
  /** Where the PATCH goes: `/sites/{id}`. */
  path: string;
  /** Fields the API refuses to change, shown read-only rather than offered. */
  locked?: Set<string>;
  onSaved: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<RecordValues>({});

  // The same layout with the untouchable fields marked read-only, so the form
  // shows them rather than hiding them: a field that vanishes in edit mode
  // reads as data lost, and the identifier is exactly the field somebody
  // checks they are on the right record by.
  const editLayout = useMemo(() => {
    if (!layout) return undefined;
    if (!locked?.size) return layout;
    return {
      ...layout,
      tabs: layout.tabs.map((tab) => ({
        ...tab,
        groups: tab.groups.map((group) => ({
          ...group,
          fields: group.fields.map((field) =>
            locked.has(field.name) ? { ...field, read_only: true } : field,
          ),
        })),
      })),
    } as FormLayout;
  }, [layout, locked]);

  const save = useAction(async () => {
    const changed: RecordValues = {};
    for (const [key, value] of Object.entries(draft)) {
      if (!locked?.has(key)) changed[key] = value;
    }
    if (Object.keys(changed).length === 0) {
      setEditing(false);
      return;
    }
    await api.patch(path, changed);
    setDraft({});
    setEditing(false);
    onSaved();
  });

  return {
    editing,
    draft,
    dirty: Object.keys(draft).length,
    layout: editing ? editLayout : layout,
    save,
    start: () => setEditing(true),
    cancel: () => {
      setDraft({});
      setEditing(false);
    },
    change: (name: string, value: unknown) =>
      setDraft((current) => ({ ...current, [name]: value })),
  };
}

/**
 * The whole thing: the buttons, the unsaved-changes note, and the card.
 *
 * `values` is the record as it came from the API, overlaid with the draft, so
 * a field being typed into shows what is being typed rather than what is
 * stored.
 */
export function EditableRecord({
  editor,
  values,
  recordId,
  mayEdit,
  hidePortals,
}: {
  editor: ReturnType<typeof useRecordEditor>;
  values: RecordValues;
  recordId?: string;
  mayEdit: boolean;
  hidePortals?: boolean;
}) {
  if (!editor.layout) return null;

  return (
    <>
      {mayEdit && (
        <div className="row-tight" style={{ marginBottom: 12 }}>
          {editor.editing ? (
            <>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => void editor.save.run()}
                disabled={editor.save.running}
              >
                {editor.save.running
                  ? "Saving…"
                  : editor.dirty
                    ? `Save ${editor.dirty} change${editor.dirty === 1 ? "" : "s"}`
                    : "Save"}
              </button>
              <button type="button" className="btn btn-sm" onClick={editor.cancel}>
                Cancel
              </button>
              {editor.dirty > 0 && (
                <span className="muted small">
                  {editor.dirty} unsaved change{editor.dirty === 1 ? "" : "s"}. Nothing is
                  written until you save.
                </span>
              )}
            </>
          ) : (
            <button type="button" className="btn btn-sm" onClick={editor.start}>
              Edit
            </button>
          )}
        </div>
      )}

      {editor.save.error && <ErrorNote message={editor.save.error} />}

      <RecordCard
        layout={editor.layout}
        values={{ ...values, ...editor.draft }}
        editing={editor.editing}
        recordId={recordId}
        hidePortals={hidePortals}
        onChange={editor.change}
      />
    </>
  );
}
