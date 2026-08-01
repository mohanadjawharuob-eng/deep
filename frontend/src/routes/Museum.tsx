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
import { RecordCard, layoutFields, type RecordValues } from "../components/RecordCard";
import {
  Badge,
  Detail,
  DetailGrid,
  Empty,
  ErrorNote,
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
          can("museum", "contributor") && (
            <Link className="btn btn-primary" to="/museum/objects/new">
              New object
            </Link>
          )
        }
      />

      <div className="toolbar">
        <SearchInput
          value={term}
          onChange={setTerm}
          placeholder="Accession number, title, maker, culture…"
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
      </div>

      {objects.loading ? (
        <Loading />
      ) : objects.error ? (
        <ErrorNote message={objects.error} onRetry={objects.reload} />
      ) : objects.data?.items.length === 0 ? (
        <Empty title="Nothing found">
          {debounced || collectionId || status || condition
            ? "No object matches these filters."
            : "The catalogue is empty. Accession an object to start it."}
        </Empty>
      ) : (
        <>
          <div className="table-wrap card">
            <table className="table table-dense">
              <thead>
                <tr>
                  <th style={{ width: "16ch" }}>Accession no.</th>
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
                      {object.number_is_legacy && (
                        <span className="badge badge-warning" title="Does not match the collection's pattern">
                          legacy
                        </span>
                      )}
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

  useEffect(() => {
    setEditing(false);
    setDraft({});
  }, [objectId]);

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

  if (layout.loading || record.loading) return <Loading rows={8} />;
  if (record.error) return <ErrorNote message={record.error} onRetry={record.reload} />;
  if (layout.error) return <ErrorNote message={layout.error} onRetry={layout.reload} />;
  if (!record.data || !layout.data || !editLayout) return null;

  const object = record.data;

  return (
    <>
      <PageHeader
        breadcrumb={[
          { label: "Catalogue", to: `/museum?${params.toString()}` },
          { label: object.accession_number },
        ]}
        title={object.title}
        subtitle={
          <span className="row-tight wrap">
            <span className="mono">{object.accession_number}</span>
            {object.number_is_legacy && <Badge value="legacy number" />}
            <Badge value={object.status} kind="status" />
            <Badge value={object.condition} kind="condition" />
            <Badge value={object.review_status} kind="review" />
          </span>
        }
        actions={
          <>
            {neighbours && (
              <div className="record-counter" aria-label="Record position">
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={!neighbours.previous}
                  onClick={() =>
                    navigate(`/museum/objects/${neighbours.previous}?${params.toString()}`)
                  }
                  aria-label="Previous record"
                >
                  ‹
                </button>
                <span className="small mono">
                  {neighbours.index + 1} / {neighbours.total}
                </span>
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={!neighbours.next}
                  onClick={() => navigate(`/museum/objects/${neighbours.next}?${params.toString()}`)}
                  aria-label="Next record"
                >
                  ›
                </button>
              </div>
            )}
            {editing ? (
              <>
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
          </>
        }
      />

      {save.error && <ErrorNote message={save.error} />}
      {editing && Object.keys(draft).length > 0 && (
        <div className="alert alert-info">
          {Object.keys(draft).length} field{Object.keys(draft).length === 1 ? "" : "s"} changed. Nothing
          is saved until you press Save.
        </div>
      )}

      <RecordCard
        layout={editing ? editLayout : layout.data}
        values={values}
        editing={editing}
        recordId={objectId}
        onChange={(name, value) => setDraft((current) => ({ ...current, [name]: value }))}
      />
    </>
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
        subtitle="Leave the accession number blank to take the next one in the collection."
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
          <Link className="btn" to={`/museum?collection_id=${item.id}`}>
            Browse objects
          </Link>
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
