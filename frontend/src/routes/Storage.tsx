/**
 * The store: the location hierarchy, and what sits in each place.
 *
 * A tree is the honest shape for Institution → Building → Floor → Room →
 * Cabinet → Shelf → Drawer → Box, so it is drawn as one. Selecting a node
 * shows its contents and how they got there — the movement history is the
 * part that matters when something is not where the record says it is.
 */

import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api, type Page, type StorageNode } from "../lib/api";
import { useQuery } from "../lib/hooks";
import {
  Detail,
  DetailGrid,
  Empty,
  ErrorNote,
  Loading,
  PageHeader,
  SearchInput,
  formatDateTime,
  humanise,
} from "../components/ui";

/**
 * One row of a location's contents. The endpoint answers across every kind of
 * thing that can be filed — finds and accessioned objects today, equipment
 * next — so the row is deliberately generic: what kind, what number, what it
 * is called.
 */
type ContentRow = {
  kind: string;
  resource_type: string;
  id: string;
  number: string;
  label: string;
};

/** Where each kind's own screen lives. */
const KIND_ROUTE: Record<string, (id: string) => string> = {
  artifacts: (id) => `/artifacts/${id}`,
  museum_objects: (id) => `/museum/objects/${id}`,
};

const KIND_LABEL: Record<string, string> = {
  artifacts: "Find",
  museum_objects: "Museum object",
};

type Movement = {
  id: string;
  resource_type: string;
  resource_id: string;
  from_path?: string | null;
  to_path?: string | null;
  reason?: string | null;
  moved_at: string;
  moved_by_label?: string | null;
};

/** How deep a kind sits, used only to pick an icon glyph. */
const KIND_GLYPH: Record<string, string> = {
  institution: "◈",
  building: "▣",
  floor: "▤",
  room: "▢",
  cabinet: "▥",
  shelf: "▬",
  drawer: "▭",
  box: "▪",
  other: "·",
};

function TreeNode({
  node,
  selected,
  onSelect,
  expanded,
  toggle,
  filter,
  depth = 0,
}: {
  node: StorageNode;
  selected: string | null;
  onSelect: (id: string) => void;
  expanded: Set<string>;
  toggle: (id: string) => void;
  filter: string;
  depth?: number;
}) {
  const matches = (candidate: StorageNode): boolean => {
    if (!filter) return true;
    const needle = filter.toLowerCase();
    if (
      candidate.name.toLowerCase().includes(needle) ||
      candidate.code.toLowerCase().includes(needle)
    ) {
      return true;
    }
    return candidate.children.some(matches);
  };

  if (!matches(node)) return null;

  const open = expanded.has(node.id) || Boolean(filter);
  const hasChildren = node.children.length > 0;

  return (
    <li>
      <div
        className={`tree-row ${selected === node.id ? "selected" : ""}`}
        // Indentation is inline because it is a function of depth, and CSS
        // cannot express "one step per ancestor" without a rule per level.
        style={{ paddingLeft: 8 + depth * 14 }}
      >
        <button
          type="button"
          className="tree-toggle"
          onClick={() => toggle(node.id)}
          aria-label={open ? "Collapse" : "Expand"}
          aria-expanded={hasChildren ? open : undefined}
          style={{ visibility: hasChildren ? "visible" : "hidden" }}
        >
          {open ? "▾" : "▸"}
        </button>
        <button type="button" className="tree-label" onClick={() => onSelect(node.id)}>
          <span className="tree-kind" aria-hidden="true" title={humanise(node.kind)}>
            {KIND_GLYPH[node.kind] ?? "·"}
          </span>
          <span className="truncate">{node.name}</span>
          {!node.is_active && <span className="badge badge-warning">inactive</span>}
          <span className="spacer" />
          <span className="tree-count">{node.code}</span>
        </button>
      </div>
      {open && hasChildren && (
        <ul className="tree-children">
          {node.children.map((child) => (
            <TreeNode
              key={child.id}
              node={child}
              selected={selected}
              onSelect={onSelect}
              expanded={expanded}
              toggle={toggle}
              filter={filter}
              depth={depth + 1}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

/**
 * A way through to the plan that draws this place — or to making one.
 *
 * The tree answers which shelf; the plan answers where the shelf is. Somebody
 * who has just found a location in the tree is exactly the person who wants
 * the second question answered.
 */
function PlanLink({ locationId }: { locationId: string }) {
  const plans = useQuery<{ id: string; name: string }[]>(
    (signal) => api.get(`/floorplans/for-location/${locationId}`, undefined, signal),
    [locationId],
  );

  if (plans.loading || !plans.data) return null;
  const first = plans.data[0];

  return first ? (
    <Link className="btn btn-sm" to={`/floorplans/${first.id}`}>
      Show on the plan
    </Link>
  ) : (
    <Link className="btn btn-sm btn-ghost" to={`/floorplans?location=${locationId}`}>
      Draw a plan
    </Link>
  );
}

export function Storage() {
  const [params, setParams] = useSearchParams();
  const selected = params.get("location");
  const [filter, setFilter] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const tree = useQuery<StorageNode[]>(
    (signal) => api.get("/storage/tree", undefined, signal),
    [],
  );

  // A store is a building, not a filesystem: a hundred-odd nodes, all of
  // which somebody wants to see at once. So the whole thing opens by default
  // unless it is genuinely large, where opening everything would bury the
  // top level under boxes.
  useEffect(() => {
    if (!tree.data) return;
    const ids: string[] = [];
    const walk = (nodes: StorageNode[]) => {
      for (const node of nodes) {
        ids.push(node.id);
        walk(node.children);
      }
    };
    walk(tree.data);

    setExpanded((current) =>
      ids.length <= 200
        ? new Set([...current, ...ids])
        : new Set([...current, ...tree.data!.map((node) => node.id)]),
    );
  }, [tree.data]);

  const contents = useQuery<Page<ContentRow>>(
    (signal) =>
      api.get(`/storage/locations/${selected}/contents`, { limit: 200 }, signal),
    [selected],
    { enabled: Boolean(selected) },
  );

  const node = useMemo(() => {
    if (!selected || !tree.data) return null;
    const find = (nodes: StorageNode[]): StorageNode | null => {
      for (const candidate of nodes) {
        if (candidate.id === selected) return candidate;
        const inner = find(candidate.children);
        if (inner) return inner;
      }
      return null;
    };
    return find(tree.data);
  }, [selected, tree.data]);

  const select = (id: string) => {
    const next = new URLSearchParams(params);
    next.set("location", id);
    setParams(next, { replace: true });
  };

  const toggle = (id: string) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <>
      <PageHeader
        title="Storage"
        subtitle="Where everything physically is, and how it got there."
      />

      <div className="split">
        <aside className="card tree-panel">
          <div className="card-body" style={{ paddingBottom: 0 }}>
            <SearchInput value={filter} onChange={setFilter} placeholder="Find a location…" />
          </div>
          {tree.loading ? (
            <div className="card-body">
              <Loading rows={6} />
            </div>
          ) : tree.error ? (
            <div className="card-body">
              <ErrorNote message={tree.error} onRetry={tree.reload} />
            </div>
          ) : tree.data?.length === 0 ? (
            <div className="card-body">
              <Empty title="No locations yet">
                Describe the store from the building down and objects can be placed in it.
              </Empty>
            </div>
          ) : (
            <ul className="tree">
              {tree.data?.map((root) => (
                <TreeNode
                  key={root.id}
                  node={root}
                  selected={selected}
                  onSelect={select}
                  expanded={expanded}
                  toggle={toggle}
                  filter={filter}
                />
              ))}
            </ul>
          )}
        </aside>

        <div className="col">
          {!selected ? (
            <Empty title="Nothing selected">Pick a location to see what is in it.</Empty>
          ) : (
            <>
              <section className="card">
                <div className="card-header" style={{ display: "block" }}>
                  <div className="small muted" style={{ marginBottom: 4 }}>
                    {node?.display_path ?? ""}
                  </div>
                  <div className="row-between wrap">
                    <h2 style={{ fontSize: "var(--text-lg)" }}>{node?.name ?? "Location"}</h2>
                    <PlanLink locationId={selected} />
                  </div>
                </div>
                <div className="card-body">
                  <DetailGrid>
                    <Detail label="Code" value={node && <span className="mono">{node.code}</span>} />
                    <Detail label="Kind" value={node && humanise(node.kind)} />
                    <Detail
                      label="Holds"
                      value={
                        contents.data
                          ? `${contents.data.total.toLocaleString()} item${contents.data.total === 1 ? "" : "s"}`
                          : null
                      }
                    />
                    <Detail label="Capacity" value={node?.capacity} />
                  </DetailGrid>
                </div>
              </section>

              {contents.loading ? (
                <Loading rows={4} />
              ) : contents.error ? (
                <ErrorNote message={contents.error} onRetry={contents.reload} />
              ) : contents.data?.items.length ? (
                <section className="card">
                  <div className="card-header">
                    <span className="card-title">Contents</span>
                    <span className="small muted">
                      including everything below this location
                    </span>
                  </div>
                  <div className="table-wrap">
                    <table className="table table-dense">
                      <thead>
                        <tr>
                          <th style={{ width: "18ch" }}>Number</th>
                          <th>Description</th>
                          <th style={{ width: "16ch" }}>Kind</th>
                        </tr>
                      </thead>
                      <tbody>
                        {contents.data.items.map((row) => {
                          const to = KIND_ROUTE[row.kind]?.(row.id);
                          return (
                            <tr key={`${row.kind}-${row.id}`}>
                              <td>
                                {to ? (
                                  <Link className="mono" to={to}>
                                    {row.number}
                                  </Link>
                                ) : (
                                  <span className="mono">{row.number}</span>
                                )}
                              </td>
                              <td>{row.label}</td>
                              <td className="muted small">
                                {KIND_LABEL[row.kind] ?? humanise(row.kind)}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </section>
              ) : (
                <div className="card">
                  <div className="card-body small muted">
                    Nothing is filed here or anywhere below it.
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}

/** The movement history of one record, reused wherever a thing can move. */
export function MovementHistory({ kind, recordId }: { kind: string; recordId: string }) {
  const history = useQuery<Page<Movement> | Movement[]>(
    (signal) => api.get(`/storage/${kind}/${recordId}/movements`, undefined, signal),
    [kind, recordId],
  );
  const rows = Array.isArray(history.data) ? history.data : (history.data?.items ?? []);

  if (history.loading) return <Loading rows={2} />;
  if (rows.length === 0) return <div className="small muted">Never moved.</div>;

  return (
    <ol className="timeline">
      {rows.map((move) => (
        <li key={move.id}>
          <div className="timeline-dot" aria-hidden="true" />
          <div>
            <div className="small">
              {move.from_path ? (
                <>
                  <span className="muted">{move.from_path}</span> → <span>{move.to_path}</span>
                </>
              ) : (
                <>Placed in {move.to_path}</>
              )}
            </div>
            <div className="small muted">
              {formatDateTime(move.moved_at)}
              {move.moved_by_label ? ` · ${move.moved_by_label}` : ""}
              {move.reason ? ` · ${humanise(move.reason)}` : ""}
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}
