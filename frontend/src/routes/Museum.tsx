/**
 * The museum module: the catalogue, the record card, and collections.
 *
 * The catalogue is a found set — a filtered list you page through — and the
 * record card carries that set with it, so ◀ ▶ walk the results rather than
 * sending you back to the list each time. That is how cataloguing actually
 * gets done: find the drawer, then work through it.
 */

import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  api,
  type Collection,
  type FormLayout,
  type MuseumObject,
  type Page,
} from "../lib/api";
import { useAction, useDebounced, useQuery, useSession } from "../lib/hooks";
import { PrintLabelButton, QrThumbnail } from "../components/labels";
import {
  RecordCard,
  RecordTabs,
  firstTab,
  layoutFields,
  type RecordValues,
} from "../components/RecordCard";
import {
  Badge,
  ConfirmDelete,
  Detail,
  DetailGrid,
  Empty,
  ErrorNote,
  ExportButton,
  LegacyMark,
  Loading,
  Pager,
  PageHeader,
  SearchInput,
  humanise,
} from "../components/ui";

const PAGE = 50;

/** Fields the backend refuses to change through a field edit, by design. */
const IMMUTABLE = new Set(["accession_number", "collection_id"]);

/** Load the layout once per screen; it is the same for every record. */
function useLayout(recordType: string) {
  return useQuery<FormLayout>(
    (signal) => api.get(`/forms/layouts/${recordType}`, undefined, signal),
    [recordType],
  );
}

/* ==========================================================================
 * Catalogue
 * ======================================================================= */
export function Catalogue() {
  const { can } = useSession();
  const [params, setParams] = useSearchParams();
  const [term, setTerm] = useState(params.get("q") ?? "");
  const debounced = useDebounced(term);

  const collectionId = params.get("collection_id") ?? "";
  const status = params.get("status") ?? "";
  const condition = params.get("condition") ?? "";
  const offset = Number(params.get("offset") ?? 0);

  // The search term lives in the URL so a found set can be shared, bookmarked,
  // and — the reason it matters here — reconstructed by the record card.
  useEffect(() => {
    const next = new URLSearchParams(params);
    if (debounced) next.set("q", debounced);
    else next.delete("q");
    if (debounced !== (params.get("q") ?? "")) {
      next.delete("offset");
      setParams(next, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced]);

  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("offset");
    setParams(next);
  };

  const collections = useQuery<Page<Collection>>(
    (signal) => api.get("/museum/collections", { limit: 200 }, signal),
    [],
  );

  const objects = useQuery<Page<MuseumObject>>(
    (signal) =>
      api.get(
        "/museum/objects",
        {
          q: debounced || undefined,
          collection_id: collectionId || undefined,
          status: status || undefined,
          condition: condition || undefined,
          limit: PAGE,
          offset,
        },
        signal,
      ),
    [debounced, collectionId, status, condition, offset],
  );

  const collectionName = (id: string) =>
    collections.data?.items.find((item) => item.id === id)?.name ?? "";

  const linkTo = (id: string) => `/museum/objects/${id}?${params.toString()}`;

  return (
    <>
      <PageHeader
        title="Catalogue"
        subtitle={
          objects.data
            ? `${objects.data.total.toLocaleString()} object${objects.data.total === 1 ? "" : "s"}`
            : "Accessioned objects"
        }
        actions={
          <>
            {/* The same records as a spreadsheet — for correcting one field
                across many objects rather than reading one closely. */}
            <Link className="btn" to="/museum/grid">
              Grid view
            </Link>
            {can("museum", "contributor") && (
              <Link className="btn btn-primary" to="/museum/objects/new">
                New object
              </Link>
            )}
          </>
        }
      />

      <div className="toolbar">
        <SearchInput
          value={term}
          onChange={setTerm}
          placeholder="Inventory number, title, maker, culture…"
        />
        <select
          className="input input-sm"
          value={collectionId}
          onChange={(event) => set("collection_id", event.target.value)}
        >
          <option value="">All collections</option>
          {collections.data?.items.map((collection) => (
            <option key={collection.id} value={collection.id}>
              {collection.name}
            </option>
          ))}
        </select>
        <select
          className="input input-sm"
          value={status}
          onChange={(event) => set("status", event.target.value)}
        >
          <option value="">Any status</option>
          {["accessioned", "on_display", "in_storage", "on_loan", "in_conservation", "missing", "deaccessioned"].map(
            (value) => (
              <option key={value} value={value}>
                {humanise(value)}
              </option>
            ),
          )}
        </select>
        <select
          className="input input-sm"
          value={condition}
          onChange={(event) => set("condition", event.target.value)}
        >
          <option value="">Any condition</option>
          {["excellent", "good", "fair", "poor", "fragmentary", "unknown"].map((value) => (
            <option key={value} value={value}>
              {humanise(value)}
            </option>
          ))}
        </select>
        {(debounced || collectionId || status || condition) && (
          <button
            type="button"
            className="filter-chip"
            onClick={() => {
              setTerm("");
              setParams(new URLSearchParams());
            }}
            title="Clear every filter"
          >
            {[
              debounced && `“${debounced}”`,
              collectionId && collectionName(collectionId),
              status && humanise(status),
              condition && humanise(condition),
            ]
              .filter(Boolean)
              .join(" · ")}
            <svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true">
              <path d="M18 6 6 18M6 6l12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        )}
      </div>

      {objects.loading ? (
        <Loading />
      ) : objects.error ? (
        <ErrorNote message={objects.error} onRetry={objects.reload} />
      ) : objects.data?.items.length === 0 ? (
        <Empty
          title={
            debounced || collectionId || status || condition
              ? "Nothing matches these filters"
              : "No objects catalogued yet"
          }
          action={
            !(debounced || collectionId || status || condition) && (
              <>
                {can("museum", "contributor") && (
                  <Link className="btn btn-primary" to="/museum/objects/new">
                    New object
                  </Link>
                )}
                {can("museum", "supervisor") && (
                  <Link className="btn" to="/museum/import">
                    Import a spreadsheet
                  </Link>
                )}
              </>
            )
          }
        >
          {debounced || collectionId || status || condition
            ? "Widen the search, or clear a filter."
            : "The catalogue starts empty. Add the first object, or import the register you already have."}
        </Empty>
      ) : (
        <>
          <div className="table-wrap card">
            <table className="table table-dense">
              <thead>
                <tr>
                  <th style={{ width: "16ch" }}>Inventory no.</th>
                  <th>Title</th>
                  <th>Collection</th>
                  <th>Type</th>
                  <th>Condition</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {objects.data?.items.map((object) => (
                  <tr key={object.id}>
                    <td>
                      <Link to={linkTo(object.id)} className="mono strong">
                        {object.accession_number}
                      </Link>
                      {object.number_is_legacy && <LegacyMark />}
                    </td>
                    <td>
                      <Link to={linkTo(object.id)}>{object.title}</Link>
                    </td>
                    <td className="muted">{collectionName(object.collection_id)}</td>
                    <td className="muted">{object.object_type ?? "—"}</td>
                    <td>
                      <Badge value={object.condition} kind="condition" />
                    </td>
                    <td>
                      <Badge value={object.status} kind="status" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager
            total={objects.data?.total ?? 0}
            limit={PAGE}
            offset={offset}
            onChange={(next) => {
              const updated = new URLSearchParams(params);
              updated.set("offset", String(next));
              setParams(updated);
            }}
          />
        </>
      )}
    </>
  );
}

/* ==========================================================================
 * One object
 * ======================================================================= */
export function ObjectDetail() {
  const { objectId = "" } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { can } = useSession();

  const layout = useLayout("museum_object");
  const record = useQuery<MuseumObject>(
    (signal) => api.get(`/museum/objects/${objectId}`, undefined, signal),
    [objectId],
  );

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<RecordValues>({});
  const [confirming, setConfirming] = useState(false);
  const [tab, setTab] = useState("");

  useEffect(() => {
    setEditing(false);
    setDraft({});
    setConfirming(false);
  }, [objectId]);

  // The tab persists across records — walking a found set with ◀ ▶ while
  // checking one tab is the whole point of the counter, and resetting to the
  // first tab on every record would undo it.
  useEffect(() => {
    if (layout.data && !layout.data.tabs.some((item) => item.key === tab)) {
      setTab(firstTab(layout.data));
    }
  }, [layout.data, tab]);

  // The found set the card walks: the same filters the list used, so ◀ ▶
  // follow the search the user actually made.
  const found = useQuery<Page<MuseumObject>>(
    (signal) =>
      api.get(
        "/museum/objects",
        {
          q: params.get("q") || undefined,
          collection_id: params.get("collection_id") || undefined,
          status: params.get("status") || undefined,
          condition: params.get("condition") || undefined,
          limit: 200,
        },
        signal,
      ),
    [params.toString()],
  );

  const neighbours = useMemo(() => {
    const items = found.data?.items ?? [];
    const index = items.findIndex((item) => item.id === objectId);
    if (index < 0) return null;
    return {
      index,
      total: found.data?.total ?? items.length,
      previous: index > 0 ? items[index - 1]!.id : null,
      next: index < items.length - 1 ? items[index + 1]!.id : null,
    };
  }, [found.data, objectId]);

  const values: RecordValues = { ...(record.data ?? {}), ...draft };

  // Identity is not a field edit: the backend refuses to renumber an object or
  // move it between collections this way, so the card must not offer to.
  const editLayout = useMemo(() => {
    if (!layout.data) return undefined;
    return {
      ...layout.data,
      tabs: layout.data.tabs.map((tab) => ({
        ...tab,
        groups: tab.groups.map((group) => ({
          ...group,
          fields: group.fields.map((field) =>
            IMMUTABLE.has(field.name) ? { ...field, read_only: true } : field,
          ),
        })),
      })),
    } as FormLayout;
  }, [layout.data]);

  const save = useAction(async () => {
    const changed: RecordValues = {};
    for (const [key, value] of Object.entries(draft)) {
      if (!IMMUTABLE.has(key)) changed[key] = value;
    }
    if (Object.keys(changed).length === 0) {
      setEditing(false);
      return;
    }
    await api.patch(`/museum/objects/${objectId}`, changed);
    setDraft({});
    setEditing(false);
    record.reload();
  });

  const remove = useAction(async () => {
    await api.delete(`/museum/objects/${objectId}`);
    navigate(`/museum?${params.toString()}`);
  });

  if (layout.loading || record.loading) return <Loading rows={8} />;
  if (record.error) return <ErrorNote message={record.error} onRetry={record.reload} />;
  if (layout.error) return <ErrorNote message={layout.error} onRetry={layout.reload} />;
  if (!record.data || !layout.data || !editLayout) return null;

  const object = record.data;

  const dirty = Object.keys(draft).length;
  const activeLayout = editing ? editLayout : layout.data;

  return (
    <>
      {/* Sticky, and it carries the tabs. Forty fields down, a cataloguer
          still knows which record they are in and can still change tab. */}
      <div className="record-head">
        <nav className="breadcrumb" aria-label="Breadcrumb">
          <Link to={`/museum?${params.toString()}`}>Museum catalogue</Link>
          <span className="breadcrumb-sep">/</span>
          <span className="mono">{object.accession_number}</span>
        </nav>

        <div className="page-header-main">
          <div className="page-header-text">
            <div className="record-title">
              <h1>{object.title}</h1>
              <span className="record-number">{object.accession_number}</span>
              {object.number_is_legacy && <LegacyMark />}
              <Badge value={object.status} kind="status" />
              <Badge value={object.condition} kind="condition" />
              {object.review_status !== "approved" && (
                <Badge value={object.review_status} kind="review" />
              )}
            </div>
            {typeof object.object_type === "string" && (
              <div className="page-subtitle">{object.object_type}</div>
            )}
          </div>

          <div className="row-tight wrap">
            {neighbours && (
              <div className="record-counter" aria-label="Position in the found set">
                <button
                  type="button"
                  disabled={!neighbours.previous}
                  onClick={() =>
                    navigate(`/museum/objects/${neighbours.previous}?${params.toString()}`)
                  }
                  aria-label="Previous record"
                  title="Previous in found set"
                >
                  ‹
                </button>
                <span className="position">
                  {neighbours.index + 1} <span className="of">of</span> {neighbours.total}
                </span>
                <button
                  type="button"
                  disabled={!neighbours.next}
                  onClick={() => navigate(`/museum/objects/${neighbours.next}?${params.toString()}`)}
                  aria-label="Next record"
                  title="Next in found set"
                >
                  ›
                </button>
              </div>
            )}

            {editing ? (
              <>
                {dirty > 0 && (
                  <span
                    className="small strong"
                    style={{ color: "var(--warn)" }}
                    aria-live="polite"
                  >
                    {dirty} unsaved
                  </span>
                )}
                <button
                  type="button"
                  className="btn"
                  disabled={save.running}
                  onClick={() => {
                    setDraft({});
                    setEditing(false);
                  }}
                >
                  Cancel
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
            ) : (
              can("museum", "contributor") && (
                <button type="button" className="btn" onClick={() => setEditing(true)}>
                  Edit
                </button>
              )
            )}
          </div>
        </div>

        {activeLayout && <RecordTabs layout={activeLayout} tab={tab} onTab={setTab} />}
      </div>

      <div className="record-body">
        <div className="record-main">
          {save.error && <ErrorNote message={save.error} />}
          {editing && dirty > 0 && (
            <div className="alert alert-warning">
              <span>
                <b>{dirty} field{dirty === 1 ? "" : "s"} changed.</b> Nothing is written until you
                press Save.
              </span>
            </div>
          )}
          {!editing && object.review_status === "pending" && (
            <div className="alert alert-warning">
              <span>
                <b>Pending</b> — submitted by a contributor and not yet approved. It is excluded
                from published counts.
              </span>
            </div>
          )}

          {activeLayout && (
            <RecordCard
              layout={activeLayout}
              values={values}
              editing={editing}
              recordId={objectId}
              tab={tab}
              onChange={(name, value) => setDraft((current) => ({ ...current, [name]: value }))}
            />
          )}
        </div>

        {/* The three things a registrar looks at *while* reading the fields:
            what it looks like, where it is, and what goes on its label. */}
        <aside className="record-aside">
          <ObjectPhoto objectId={objectId} />
          <CurrentLocation object={object} />

          <div className="card">
            <div className="card-body">
              <div className="overline" style={{ marginBottom: 8 }}>
                Label &amp; QR
              </div>
              <div className="row-tight">
                <QrThumbnail path={`/museum/objects/${objectId}/qr.png`} />
                <PrintLabelButton
                  className="btn btn-sm label-print-btn"
                  details={{
                    number: object.accession_number,
                    name: object.title,
                    context: object.collection_name,
                    note: object.storage_path,
                    qrPath: `/museum/objects/${objectId}/qr.png`,
                  }}
                />
              </div>
            </div>
          </div>

          {can("museum", "supervisor") && (
            <button
              type="button"
              className="btn btn-danger btn-sm"
              onClick={() => setConfirming(true)}
            >
              Delete {object.accession_number}…
            </button>
          )}
        </aside>
      </div>

      {confirming && (
        <ConfirmDelete
          name={object.accession_number}
          title="Delete this object?"
          consequences={
            <>
              Its conservation history and photographs are deleted with it. Deaccessioning rather
              than deleting keeps the record.
            </>
          }
          busy={remove.running}
          onCancel={() => setConfirming(false)}
          onConfirm={() => void remove.run()}
        />
      )}
    </>
  );
}

/** The primary photograph, or an honest placeholder. */
function ObjectPhoto({ objectId }: { objectId: string }) {
  const photos = useQuery<Page<{ id: string; title: string }>>(
    (signal) => api.get("/photographs", { museum_object_id: objectId, limit: 4 }, signal),
    [objectId],
  );
  const first = photos.data?.items[0];

  return (
    <div className="card">
      <div className="record-photo">
        {first ? (
          <img src={`/api/v1/photographs/${first.id}/thumbnail?size=600`} alt={first.title} />
        ) : (
          "No photograph"
        )}
      </div>
      <div className="card-body" style={{ padding: "8px 12px" }}>
        <span className="small muted">
          {photos.data?.total
            ? `${photos.data.total} photograph${photos.data.total === 1 ? "" : "s"} · primary shown`
            : "None uploaded"}
        </span>
      </div>
    </div>
  );
}

/**
 * A link to the plan that draws where this object is.
 *
 * The plan of the *room* is what has the cabinet on it, not the plan of the
 * box — so the backend walks up the hierarchy to find it. Rendered only when
 * one exists; a dead link to a plan nobody has drawn is worse than nothing.
 */
function PlanShortcut({ locationId }: { locationId: string }) {
  const plans = useQuery<{ id: string; name: string }[]>(
    (signal) => api.get(`/floorplans/for-location/${locationId}`, undefined, signal),
    [locationId],
  );
  const first = plans.data?.[0];
  if (!first) return null;

  return (
    <Link className="btn btn-sm" to={`/floorplans/${first.id}`} style={{ marginTop: 6, width: "100%" }}>
      Show on the floor plan
    </Link>
  );
}

/** Where the object is, spelled out rather than as one long path. */
function CurrentLocation({ object }: { object: MuseumObject }) {
  const locationId = object.storage_location_id;
  const location = useQuery<{ display_path: string }>(
    (signal) => api.get(`/storage/locations/${locationId}`, undefined, signal),
    [locationId],
    { enabled: Boolean(locationId) },
  );

  return (
    <div className="card">
      <div className="card-body">
        <div className="overline" style={{ marginBottom: 7 }}>
          Current location
        </div>
        {!locationId ? (
          <div className="small muted">Not filed in the store.</div>
        ) : location.loading ? (
          <div className="small muted">…</div>
        ) : (
          <>
            <div className="small" style={{ lineHeight: "var(--leading-prose)", color: "var(--text-2)" }}>
              {(location.data?.display_path ?? "").split("→").map((part, index) => (
                <span key={index}>
                  {part.trim()}
                  <br />
                </span>
              ))}
            </div>
            <Link
              className="btn btn-sm"
              to={`/storage?location=${locationId}`}
              style={{ marginTop: 9, width: "100%" }}
            >
              Show in storage tree
            </Link>
            <PlanShortcut locationId={locationId} />
          </>
        )}
      </div>
    </div>
  );
}

/* ==========================================================================
 * A new object
 * ======================================================================= */
export function NewObject() {
  const navigate = useNavigate();
  const layout = useLayout("museum_object");
  const [values, setValues] = useState<RecordValues>({});

  const collectionId = values.collection_id as string | undefined;

  // Show what number the object will get before it gets one — the single most
  // asked question when accessioning.
  const preview = useQuery<{ next_accession_number: string; pattern: string | null }>(
    (signal) => api.get(`/museum/collections/${collectionId}/next-number`, undefined, signal),
    [collectionId],
    { enabled: Boolean(collectionId) },
  );

  const create = useAction(async () => {
    const known = new Set(layoutFields(layout.data!).map((field) => field.name));
    const payload: RecordValues = {};
    for (const [key, value] of Object.entries(values)) {
      if (known.has(key) && value !== null && value !== undefined && value !== "") {
        payload[key] = value;
      }
    }
    const created = await api.post<MuseumObject>("/museum/objects", payload);
    navigate(`/museum/objects/${created.id}`);
  });

  if (layout.loading) return <Loading rows={8} />;
  if (layout.error || !layout.data) {
    return <ErrorNote message={layout.error ?? "No layout"} onRetry={layout.reload} />;
  }

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Catalogue", to: "/museum" }, { label: "New object" }]}
        title="New object"
        subtitle="Leave the inventory number blank to take the next one in the collection."
        actions={
          <>
            <button type="button" className="btn" onClick={() => navigate("/museum")}>
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={create.running}
              onClick={() => void create.run()}
            >
              {create.running ? "Creating…" : "Create"}
            </button>
          </>
        }
      />

      {create.error && <ErrorNote message={create.error} />}
      {collectionId && preview.data && !values.accession_number && (
        <div className="alert alert-info">
          This object will be numbered{" "}
          <span className="mono strong">{preview.data.next_accession_number}</span>.
        </div>
      )}

      <RecordCard
        layout={layout.data}
        values={values}
        editing
        hidePortals
        onChange={(name, value) => setValues((current) => ({ ...current, [name]: value }))}
      />
    </>
  );
}

/* ==========================================================================
 * Collections
 * ======================================================================= */
export function Collections() {
  const { can } = useSession();
  const collections = useQuery<Page<Collection>>(
    (signal) => api.get("/museum/collections", { limit: 200 }, signal),
    [],
  );

  return (
    <>
      <PageHeader
        title="Collections"
        subtitle="Each collection numbers its own objects."
        actions={
          can("museum", "supervisor") && (
            <Link className="btn btn-primary" to="/museum/collections/new">
              New collection
            </Link>
          )
        }
      />

      {collections.loading ? (
        <Loading />
      ) : collections.error ? (
        <ErrorNote message={collections.error} onRetry={collections.reload} />
      ) : collections.data?.items.length === 0 ? (
        <Empty title="No collections yet">
          A collection holds objects and decides how they are numbered.
        </Empty>
      ) : (
        <div className="card-grid">
          {collections.data?.items.map((collection) => (
            <Link key={collection.id} to={`/museum/collections/${collection.id}`} className="card card-link">
              <div className="card-body">
                <div className="row-between">
                  <span className="strong">{collection.name}</span>
                  <span className="badge">{collection.code}</span>
                </div>
                <div className="small muted" style={{ marginTop: "var(--space-2)" }}>
                  {collection.institution ?? "—"}
                </div>
                <div className="row-between small" style={{ marginTop: "var(--space-3)" }}>
                  <span className="muted">
                    {(collection.object_count ?? 0).toLocaleString()} object
                    {collection.object_count === 1 ? "" : "s"}
                  </span>
                  <span className="mono muted">{collection.next_accession_number ?? ""}</span>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}

export function CollectionDetail() {
  const { collectionId = "" } = useParams();
  const collection = useQuery<Collection>(
    (signal) => api.get(`/museum/collections/${collectionId}`, undefined, signal),
    [collectionId],
  );
  const objects = useQuery<Page<MuseumObject>>(
    (signal) => api.get("/museum/objects", { collection_id: collectionId, limit: 10 }, signal),
    [collectionId],
  );

  if (collection.loading) return <Loading rows={6} />;
  if (collection.error) return <ErrorNote message={collection.error} onRetry={collection.reload} />;
  if (!collection.data) return null;

  const item = collection.data;

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Collections", to: "/museum/collections" }, { label: item.name }]}
        title={item.name}
        subtitle={item.institution}
        actions={
          <>
            <Link className="btn" to={`/museum?collection_id=${item.id}`}>
              Browse objects
            </Link>
            <ExportButton
              path={`/exports/collections/${item.id}.xlsx`}
              label="Export everything"
            />
          </>
        }
      />

      <section className="card">
        <div className="card-body">
          <DetailGrid>
            <Detail label="Code" value={<span className="mono">{item.code}</span>} />
            <Detail
              label="Numbering pattern"
              value={<span className="mono">{item.accession_pattern ?? "—"}</span>}
            />
            <Detail label="Prefix" value={item.accession_prefix} />
            <Detail label="Next number" value={<span className="mono">{item.next_accession_number}</span>} />
            <Detail label="Sequence" value={item.accession_sequence} />
            <Detail
              label="Pattern enforced"
              value={
                item.enforce_pattern
                  ? "Yes — a number that does not match is refused"
                  : "No — a number that does not match is recorded and flagged"
              }
              span={2}
            />
            <Detail label="Objects" value={(item.object_count ?? 0).toLocaleString()} />
          </DetailGrid>
        </div>
      </section>

      <section className="card" style={{ marginTop: "var(--space-5)" }}>
        <div className="card-header">
          <span className="card-title">Recent objects</span>
          <Link className="small" to={`/museum?collection_id=${item.id}`}>
            All
          </Link>
        </div>
        {objects.loading ? (
          <div className="card-body">
            <Loading rows={3} />
          </div>
        ) : objects.data?.items.length ? (
          <div className="table-wrap">
            <table className="table table-dense">
              <tbody>
                {objects.data.items.map((object) => (
                  <tr key={object.id}>
                    <td style={{ width: "16ch" }}>
                      <Link className="mono" to={`/museum/objects/${object.id}`}>
                        {object.accession_number}
                      </Link>
                    </td>
                    <td>
                      <Link to={`/museum/objects/${object.id}`}>{object.title}</Link>
                    </td>
                    <td style={{ width: 1 }}>
                      <Badge value={object.status} kind="status" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="card-body small muted">No objects in this collection yet.</div>
        )}
      </section>
    </>
  );
}
