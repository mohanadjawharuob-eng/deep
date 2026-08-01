/**
 * The floor plan: where the store is, drawn.
 *
 * The tree answers *which* shelf an object is on. This answers *where that
 * shelf is*, which is the question somebody standing in the doorway of an
 * unfamiliar room actually has.
 *
 * Two things are load-bearing:
 *
 * **The plan holds no inventory.** A rectangle says "I am Cabinet 4", and what
 * Cabinet 4 contains is read from the store every time the plan is opened. So
 * moving a box updates the drawing without anybody redrawing it, and a plan
 * cannot go stale.
 *
 * **Coordinates are fractions, not pixels.** Everything is stored as 0–1 of
 * the plan's extent, so the drawing scales to whatever width the screen gives
 * it and survives its background scan being replaced with a better one.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { api, type Page, type StorageNode } from "../lib/api";
import { useAction, useQuery, useSession } from "../lib/hooks";
import {
  ConfirmDelete,
  Empty,
  ErrorNote,
  Loading,
  PageHeader,
  humanise,
} from "../components/ui";

/* --------------------------------------------------------------------------
 * Shapes
 * ----------------------------------------------------------------------- */
type ShapeKind = "rect" | "polygon" | "circle" | "pin" | "wall" | "label";

type Shape = {
  id?: string;
  kind: ShapeKind;
  points: [number, number][];
  label: string | null;
  colour: string | null;
  rotation: number;
  z_index: number;
  location_id: string | null;
  resource_type?: string | null;
  resource_id?: string | null;
  notes: string | null;
  location_name?: string | null;
  location_path?: string | null;
  item_count?: number | null;
};

type Plan = {
  id: string;
  location_id: string;
  name: string;
  description: string | null;
  image_url: string | null;
  image_width: number | null;
  image_height: number | null;
  width_m: number | null;
  height_m: number | null;
  is_default: boolean;
  location_name: string | null;
  location_path: string | null;
  shape_count: number;
  shapes: Shape[];
};

/** The palette a shape may take, as token names rather than hexes. */
const COLOURS = ["accent", "info", "ok", "warn", "danger", "neutral"] as const;

const TOKEN: Record<string, string> = {
  accent: "var(--accent)",
  info: "var(--info)",
  ok: "var(--ok)",
  warn: "var(--warn)",
  danger: "var(--danger)",
  neutral: "var(--text-3)",
};

const TOOLS: { kind: ShapeKind; label: string; hint: string }[] = [
  { kind: "rect", label: "Case", hint: "A cabinet, case or shelf run — drag a rectangle" },
  { kind: "wall", label: "Wall", hint: "Scenery, so the room can be recognised" },
  { kind: "pin", label: "Pin", hint: "A single spot, for something standing on the floor" },
  { kind: "label", label: "Text", hint: "A note on the drawing" },
];

function colourOf(shape: Shape) {
  return TOKEN[shape.colour ?? "accent"] ?? TOKEN.accent!;
}

/* ==========================================================================
 * The screen
 * ======================================================================= */
export function FloorPlanScreen() {
  const { planId = "" } = useParams();
  const { can } = useSession();
  const mayDraw = can("archaeology", "supervisor");

  const plan = useQuery<Plan>(
    (signal) => api.get(`/floorplans/${planId}`, undefined, signal),
    [planId],
  );
  const tree = useQuery<StorageNode[]>((signal) => api.get("/storage/tree", undefined, signal), []);

  const [editing, setEditing] = useState(false);
  const [shapes, setShapes] = useState<Shape[] | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [tool, setTool] = useState<ShapeKind>("rect");
  const [confirming, setConfirming] = useState(false);

  const current = shapes ?? plan.data?.shapes ?? [];

  useEffect(() => {
    setShapes(null);
    setSelected(null);
    setEditing(false);
  }, [planId]);

  const save = useAction(async () => {
    const body = {
      shapes: current.map((shape, index) => ({
        kind: shape.kind,
        points: shape.points,
        label: shape.label,
        colour: shape.colour,
        rotation: shape.rotation,
        z_index: index,
        location_id: shape.location_id,
        notes: shape.notes,
      })),
    };
    await api.put(`/floorplans/${planId}/shapes`, body);
    setShapes(null);
    setEditing(false);
    setSelected(null);
    plan.reload();
  });

  if (plan.loading) return <Loading rows={8} />;
  if (plan.error) return <ErrorNote message={plan.error} onRetry={plan.reload} />;
  if (!plan.data) return null;

  const record = plan.data;
  const dirty = shapes !== null;

  return (
    <>
      <PageHeader
        breadcrumb={[
          { label: "Storage", to: "/storage" },
          { label: record.location_name ?? "Location", to: `/storage?location=${record.location_id}` },
          { label: record.name },
        ]}
        title={record.name}
        subtitle={
          <span className="row-tight wrap">
            <span>{record.location_path}</span>
            {record.width_m && record.height_m && (
              <span className="mono">
                {record.width_m} × {record.height_m} m
              </span>
            )}
            <span>
              {current.length} shape{current.length === 1 ? "" : "s"}
            </span>
          </span>
        }
        actions={
          mayDraw && (
            <>
              {editing ? (
                <>
                  {dirty && (
                    <span className="small strong" style={{ color: "var(--warn)" }}>
                      unsaved
                    </span>
                  )}
                  <button
                    type="button"
                    className="btn"
                    onClick={() => {
                      setShapes(null);
                      setSelected(null);
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
                    {save.running ? "Saving…" : "Save plan"}
                  </button>
                </>
              ) : (
                <button type="button" className="btn" onClick={() => setEditing(true)}>
                  Edit plan
                </button>
              )}
            </>
          )
        }
      />

      {save.error && <ErrorNote message={save.error} />}

      <div className="plan-layout">
        <PlanCanvas
          plan={record}
          shapes={current}
          editing={editing}
          tool={tool}
          selected={selected}
          onSelect={setSelected}
          onChange={setShapes}
        />

        <aside className="col">
          {editing && (
            <section className="card">
              <div className="card-header">
                <span className="card-title">Draw</span>
              </div>
              <div className="card-body">
                <div className="row-tight wrap">
                  {TOOLS.map((option) => (
                    <button
                      key={option.kind}
                      type="button"
                      className={`btn btn-sm ${tool === option.kind ? "btn-primary" : ""}`}
                      title={option.hint}
                      onClick={() => setTool(option.kind)}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
                <p className="small muted" style={{ marginTop: 8 }}>
                  {TOOLS.find((option) => option.kind === tool)?.hint}
                </p>
              </div>
            </section>
          )}

          {selected !== null && current[selected] ? (
            <ShapeInspector
              shape={current[selected]!}
              tree={tree.data ?? []}
              editing={editing}
              onChange={(next) =>
                setShapes(current.map((shape, index) => (index === selected ? next : shape)))
              }
              onDelete={() => {
                setShapes(current.filter((_, index) => index !== selected));
                setSelected(null);
              }}
            />
          ) : (
            <section className="card">
              <div className="card-body small muted">
                {editing
                  ? "Drag on the plan to draw. Click a shape to say which place it is."
                  : "Click a case on the plan to see what is in it."}
              </div>
            </section>
          )}

          {!editing && <PlanLegend shapes={current} />}

          {mayDraw && !editing && (
            <button type="button" className="btn btn-danger btn-sm" onClick={() => setConfirming(true)}>
              Delete this plan…
            </button>
          )}
        </aside>
      </div>

      {confirming && (
        <ConfirmDelete
          name={record.name}
          title="Delete this plan?"
          consequences={
            <>The locations it draws are untouched — a plan is a picture of the store, not the store.</>
          }
          onCancel={() => setConfirming(false)}
          onConfirm={async () => {
            await api.delete(`/floorplans/${record.id}`);
            window.location.assign(`/storage?location=${record.location_id}`);
          }}
        />
      )}
    </>
  );
}

/* --------------------------------------------------------------------------
 * The canvas
 * ----------------------------------------------------------------------- */
function PlanCanvas({
  plan,
  shapes,
  editing,
  tool,
  selected,
  onSelect,
  onChange,
}: {
  plan: Plan;
  shapes: Shape[];
  editing: boolean;
  tool: ShapeKind;
  selected: number | null;
  onSelect: (index: number | null) => void;
  onChange: (shapes: Shape[]) => void;
}) {
  const surface = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{ from: [number, number]; to: [number, number] } | null>(null);

  /** Pointer position as a fraction of the plan, clamped to it. */
  const fraction = useCallback((event: React.PointerEvent): [number, number] => {
    const box = surface.current!.getBoundingClientRect();
    return [
      Math.min(1, Math.max(0, (event.clientX - box.left) / box.width)),
      Math.min(1, Math.max(0, (event.clientY - box.top) / box.height)),
    ];
  }, []);

  const aspect =
    plan.image_width && plan.image_height
      ? plan.image_height / plan.image_width
      : plan.width_m && plan.height_m
        ? Number(plan.height_m) / Number(plan.width_m)
        : 0.66;

  const onDown = (event: React.PointerEvent) => {
    if (!editing) return;
    if ((event.target as HTMLElement).closest("[data-shape]")) return;

    const point = fraction(event);
    if (tool === "pin" || tool === "label") {
      onChange([
        ...shapes,
        {
          kind: tool,
          points: [point],
          label: tool === "label" ? "Text" : null,
          colour: tool === "pin" ? "accent" : "neutral",
          rotation: 0,
          z_index: shapes.length,
          location_id: null,
          notes: null,
        },
      ]);
      onSelect(shapes.length);
      return;
    }
    setDrag({ from: point, to: point });
    (event.target as HTMLElement).setPointerCapture(event.pointerId);
  };

  const onMove = (event: React.PointerEvent) => {
    if (drag) setDrag({ ...drag, to: fraction(event) });
  };

  const onUp = () => {
    if (!drag) return;
    const [x1, y1] = drag.from;
    const [x2, y2] = drag.to;

    // A click that did not travel is not a rectangle. Without this, every
    // stray click leaves an invisible zero-size shape on the plan.
    if (Math.abs(x2 - x1) > 0.01 && Math.abs(y2 - y1) > 0.01) {
      const points: [number, number][] =
        tool === "wall"
          ? [
              [Math.min(x1, x2), Math.min(y1, y2)],
              [Math.max(x1, x2), Math.min(y1, y2)],
              [Math.max(x1, x2), Math.max(y1, y2)],
              [Math.min(x1, x2), Math.max(y1, y2)],
            ]
          : [
              [Math.min(x1, x2), Math.min(y1, y2)],
              [Math.max(x1, x2), Math.max(y1, y2)],
            ];

      onChange([
        ...shapes,
        {
          kind: tool === "wall" ? "wall" : "rect",
          points,
          label: null,
          colour: tool === "wall" ? "neutral" : "accent",
          rotation: 0,
          z_index: shapes.length,
          location_id: null,
          notes: null,
        },
      ]);
      onSelect(shapes.length);
    }
    setDrag(null);
  };

  const preview = drag
    ? {
        left: `${Math.min(drag.from[0], drag.to[0]) * 100}%`,
        top: `${Math.min(drag.from[1], drag.to[1]) * 100}%`,
        width: `${Math.abs(drag.to[0] - drag.from[0]) * 100}%`,
        height: `${Math.abs(drag.to[1] - drag.from[1]) * 100}%`,
      }
    : null;

  return (
    <div className="card plan-card">
      <div
        ref={surface}
        className={`plan-surface ${editing ? "editing" : ""}`}
        style={{ aspectRatio: `1 / ${aspect}` }}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
      >
        {plan.image_url ? (
          <img className="plan-image" src={plan.image_url} alt="" draggable={false} />
        ) : (
          <div className="plan-grid" aria-hidden="true" />
        )}

        {shapes.map((shape, index) => (
          <PlanShape
            key={shape.id ?? index}
            shape={shape}
            active={index === selected}
            editing={editing}
            onSelect={() => onSelect(index)}
            onMove={(delta) => {
              onChange(
                shapes.map((item, position) =>
                  position === index
                    ? {
                        ...item,
                        points: item.points.map(([x, y]) => [
                          Math.min(1, Math.max(0, x + delta[0])),
                          Math.min(1, Math.max(0, y + delta[1])),
                        ]) as [number, number][],
                      }
                    : item,
                ),
              );
            }}
          />
        ))}

        {preview && <div className="plan-preview" style={preview} />}
      </div>

      {plan.width_m && (
        <div className="plan-scale">
          <span className="scale-bar" style={{ width: `${(1 / Number(plan.width_m)) * 100}%` }} />
          <span className="small muted mono">1 m</span>
        </div>
      )}
    </div>
  );
}

/** One shape on the plan. */
function PlanShape({
  shape,
  active,
  editing,
  onSelect,
  onMove,
}: {
  shape: Shape;
  active: boolean;
  editing: boolean;
  onSelect: () => void;
  onMove: (delta: [number, number]) => void;
}) {
  const dragging = useRef<{ x: number; y: number; width: number; height: number } | null>(null);
  const colour = colourOf(shape);
  const empty = shape.location_id !== null && (shape.item_count ?? 0) === 0;

  const start = (event: React.PointerEvent) => {
    event.stopPropagation();
    onSelect();
    if (!editing) return;
    const box = (event.currentTarget as HTMLElement).parentElement!.getBoundingClientRect();
    dragging.current = { x: event.clientX, y: event.clientY, width: box.width, height: box.height };
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
  };

  const move = (event: React.PointerEvent) => {
    const state = dragging.current;
    if (!state) return;
    onMove([
      (event.clientX - state.x) / state.width,
      (event.clientY - state.y) / state.height,
    ]);
    dragging.current = { ...state, x: event.clientX, y: event.clientY };
  };

  const stop = () => {
    dragging.current = null;
  };

  const handlers = {
    "data-shape": true,
    onPointerDown: start,
    onPointerMove: move,
    onPointerUp: stop,
  } as const;

  if (shape.kind === "pin") {
    const [x, y] = shape.points[0] ?? [0.5, 0.5];
    return (
      <button
        type="button"
        {...handlers}
        className={`plan-pin ${active ? "active" : ""}`}
        style={{ left: `${x! * 100}%`, top: `${y! * 100}%`, color: colour }}
        title={shape.label ?? "Pin"}
      >
        <span className="plan-pin-dot" />
        {shape.label && <span className="plan-pin-label">{shape.label}</span>}
      </button>
    );
  }

  if (shape.kind === "label") {
    const [x, y] = shape.points[0] ?? [0.5, 0.5];
    return (
      <button
        type="button"
        {...handlers}
        className={`plan-label ${active ? "active" : ""}`}
        style={{ left: `${x! * 100}%`, top: `${y! * 100}%` }}
      >
        {shape.label ?? "Text"}
      </button>
    );
  }

  const xs = shape.points.map((point) => point[0]);
  const ys = shape.points.map((point) => point[1]);
  const left = Math.min(...xs);
  const top = Math.min(...ys);

  return (
    <button
      type="button"
      {...handlers}
      className={`plan-rect ${shape.kind === "wall" ? "wall" : ""} ${active ? "active" : ""} ${
        empty ? "empty" : ""
      }`}
      style={{
        left: `${left * 100}%`,
        top: `${top * 100}%`,
        width: `${(Math.max(...xs) - left) * 100}%`,
        height: `${(Math.max(...ys) - top) * 100}%`,
        // The colour is the shape's; the fill is derived so a dense plan does
        // not become six flat blocks of paint.
        borderColor: colour,
        background: `color-mix(in srgb, ${colour} 14%, transparent)`,
      }}
      title={shape.location_path ?? shape.label ?? undefined}
    >
      <span className="plan-rect-text">
        {shape.label ?? shape.location_name ?? ""}
        {shape.item_count !== null && shape.item_count !== undefined && (
          <span className="plan-rect-count mono">{shape.item_count}</span>
        )}
      </span>
    </button>
  );
}

/* --------------------------------------------------------------------------
 * The inspector
 * ----------------------------------------------------------------------- */
function ShapeInspector({
  shape,
  tree,
  editing,
  onChange,
  onDelete,
}: {
  shape: Shape;
  tree: StorageNode[];
  editing: boolean;
  onChange: (shape: Shape) => void;
  onDelete: () => void;
}) {
  /** The tree, flattened to an indented list a <select> can hold. */
  const options = useMemo(() => {
    const rows: { id: string; label: string }[] = [];
    const walk = (nodes: StorageNode[], depth: number) => {
      for (const node of nodes) {
        rows.push({ id: node.id, label: `${"  ".repeat(depth)}${node.name}` });
        walk(node.children, depth + 1);
      }
    };
    walk(tree, 0);
    return rows;
  }, [tree]);

  const contents = useQuery<Page<{ id: string; kind: string; number: string; label: string }>>(
    (signal) =>
      api.get(`/storage/locations/${shape.location_id}/contents`, { limit: 50 }, signal),
    [shape.location_id],
    { enabled: Boolean(shape.location_id) && !editing },
  );

  return (
    <section className="card">
      <div className="card-header">
        <span className="card-title">
          {shape.location_name ?? shape.label ?? humanise(shape.kind)}
        </span>
        {editing && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={onDelete}>
            Remove
          </button>
        )}
      </div>

      <div className="card-body">
        {editing ? (
          <div className="col">
            <div className="field">
              <label className="field-label">Label</label>
              <input
                className="input"
                value={shape.label ?? ""}
                placeholder="Case 7"
                onChange={(event) => onChange({ ...shape, label: event.target.value || null })}
              />
            </div>

            {shape.kind !== "wall" && shape.kind !== "label" && (
              <div className="field">
                <label className="field-label">This shape is</label>
                <select
                  className="input"
                  value={shape.location_id ?? ""}
                  onChange={(event) =>
                    onChange({ ...shape, location_id: event.target.value || null })
                  }
                >
                  <option value="">Nothing in particular — scenery</option>
                  {options.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <div className="field-help">
                  Linking a shape to a place is what makes the plan useful: it then shows what that
                  place holds, and keeps showing the right thing when objects move.
                </div>
              </div>
            )}

            <div className="field">
              <label className="field-label">Colour</label>
              <div className="row-tight wrap">
                {COLOURS.map((name) => (
                  <button
                    key={name}
                    type="button"
                    className={`swatch ${shape.colour === name ? "active" : ""}`}
                    style={{ background: TOKEN[name] }}
                    title={humanise(name)}
                    aria-label={humanise(name)}
                    onClick={() => onChange({ ...shape, colour: name })}
                  />
                ))}
              </div>
            </div>
          </div>
        ) : shape.location_id ? (
          <>
            <div className="overline">{shape.location_name}</div>
            <div className="small muted" style={{ marginBottom: 8 }}>
              {shape.location_path}
            </div>

            {contents.loading ? (
              <div className="small muted">Loading…</div>
            ) : contents.data?.items.length ? (
              <ul className="plan-contents">
                {contents.data.items.map((item) => (
                  <li key={item.id}>
                    <Link
                      className="mono small"
                      to={
                        item.kind === "museum_objects"
                          ? `/museum/objects/${item.id}`
                          : `/artifacts/${item.id}`
                      }
                    >
                      {item.number}
                    </Link>
                    <span className="small muted truncate">{item.label}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="small muted">Nothing is filed here.</div>
            )}

            <Link
              className="btn btn-sm"
              to={`/storage?location=${shape.location_id}`}
              style={{ marginTop: 10, width: "100%" }}
            >
              Open in the storage tree
            </Link>
          </>
        ) : (
          <div className="small muted">
            {shape.label ?? "Scenery"} — not linked to a place in the store.
          </div>
        )}
      </div>
    </section>
  );
}

/** What the colours on this plan mean, built from the plan itself. */
function PlanLegend({ shapes }: { shapes: Shape[] }) {
  const linked = shapes.filter((shape) => shape.location_id);
  const empty = linked.filter((shape) => (shape.item_count ?? 0) === 0).length;

  if (linked.length === 0) return null;

  return (
    <section className="card">
      <div className="card-body">
        <div className="overline" style={{ marginBottom: 7 }}>
          On this plan
        </div>
        <div className="small">
          {linked.length} place{linked.length === 1 ? "" : "s"} drawn,{" "}
          {linked.reduce((total, shape) => total + (shape.item_count ?? 0), 0).toLocaleString()}{" "}
          item{linked.length === 1 ? "" : "s"} in them.
        </div>
        {empty > 0 && (
          <div className="small muted" style={{ marginTop: 4 }}>
            {empty} drawn {empty === 1 ? "place is" : "places are"} empty, shown hollow.
          </div>
        )}
      </div>
    </section>
  );
}

/* ==========================================================================
 * Plans of a location, and making a new one
 * ======================================================================= */
export function FloorPlansForLocation() {
  const [params] = useSearchParams();
  const locationId = params.get("location") ?? "";
  const { can } = useSession();

  const plans = useQuery<Page<Plan>>(
    (signal) => api.get("/floorplans", { location_id: locationId || undefined }, signal),
    [locationId],
  );

  const [name, setName] = useState("");
  const create = useAction(async () => {
    const plan = await api.post<Plan>("/floorplans", {
      location_id: locationId,
      name: name || "Plan",
    });
    window.location.assign(`/floorplans/${plan.id}`);
  });

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Storage", to: "/storage" }, { label: "Plans" }]}
        title="Floor plans"
        subtitle="Where the store is, drawn — so a shelf can be found by somebody who has never been in the room."
      />

      {create.error && <ErrorNote message={create.error} />}

      {plans.loading ? (
        <Loading />
      ) : plans.data?.items.length ? (
        <div className="card-grid">
          {plans.data.items.map((plan) => (
            <Link key={plan.id} to={`/floorplans/${plan.id}`} className="card card-link">
              <div className="card-body">
                <div className="row-between">
                  <span className="strong">{plan.name}</span>
                  {plan.is_default && <span className="badge badge-accent">default</span>}
                </div>
                <div className="small muted" style={{ marginTop: 4 }}>
                  {plan.location_path}
                </div>
                <div className="small muted" style={{ marginTop: 8 }}>
                  {plan.shape_count} shape{plan.shape_count === 1 ? "" : "s"}
                  {plan.image_url ? " · has a background" : " · drawn from nothing"}
                </div>
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <Empty title="No plans yet">
          A plan draws one room or floor and says which cabinet is which. It holds no inventory of
          its own, so it cannot go out of date.
        </Empty>
      )}

      {can("archaeology", "supervisor") && locationId && (
        <section className="card" style={{ marginTop: "var(--space-5)" }}>
          <div className="card-header">
            <span className="card-title">New plan</span>
          </div>
          <div className="card-body">
            <div className="row-tight wrap">
              <input
                className="input"
                style={{ maxWidth: "22rem" }}
                value={name}
                placeholder="Gallery 2 — ground floor"
                onChange={(event) => setName(event.target.value)}
              />
              <button
                type="button"
                className="btn btn-primary"
                disabled={create.running}
                onClick={() => void create.run()}
              >
                {create.running ? "Creating…" : "Create"}
              </button>
            </div>
          </div>
        </section>
      )}
    </>
  );
}
