/**
 * The store: kit, stock, and the packing lists that turn both into a kit bag.
 *
 * Four screens, arranged around the questions people actually walk in with:
 *
 * - **Equipment** — "where is the Leica", and "who has it".
 * - **Stock** — "how many finds bags are left", and "what do we need to order".
 * - **Packing lists** — "what does a trench need for a day".
 * - **Kits** — "what went out this morning, and what was it short of".
 *
 * The shortfall list is the part worth reading twice. Building a kit does not
 * fail when the store cannot supply everything; it hands over what there is
 * and says plainly what is missing, because a kit that is nine tenths ready is
 * still the kit going out, and the person loading the van needs the list
 * rather than an error.
 */

import { useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  api,
  type Calibration,
  type Checkout,
  type Consumable,
  type ConsumableDetail,
  type Equipment,
  type EquipmentDetail,
  type Kit,
  type KitDetail,
  type KitTemplate,
  type KitTemplateDetail,
  type FormLayout,
  type Page,
  type StockMovement,
} from "../lib/api";
import { useAction, useDebounced, useQuery, useSession } from "../lib/hooks";
import { RecordCard, writableKeys, type RecordValues } from "../components/RecordCard";
import {
  Badge,
  ConfirmDelete,
  Detail,
  DetailGrid,
  Empty,
  ErrorNote,
  Loading,
  Pager,
  PageHeader,
  SearchInput,
  formatDate,
  formatDateTime,
  humanise,
} from "../components/ui";

const PAGE = 50;

/** A quantity as somebody would write it: 1, not 1.000. */
function amount(value: number | string | null | undefined) {
  const parsed = typeof value === "string" ? Number(value) : (value ?? 0);
  return Number.isFinite(parsed) ? String(Number(parsed.toFixed(3))) : "0";
}

/* ==========================================================================
 * Equipment
 * ======================================================================= */
export function EquipmentList() {
  const { can } = useSession();
  const [params, setParams] = useSearchParams();
  const [term, setTerm] = useState(params.get("q") ?? "");
  const debounced = useDebounced(term);

  const view = params.get("view") ?? "all";
  const offset = Number(params.get("offset") ?? 0);
  const category = params.get("category") ?? "";

  const categories = useQuery<string[]>(
    (signal) => api.get("/inventory/equipment/categories", undefined, signal),
    [],
  );

  const items = useQuery<Page<Equipment>>(
    (signal) =>
      api.get(
        "/inventory/equipment",
        {
          q: debounced || undefined,
          category: category || undefined,
          available: view === "available" ? true : undefined,
          calibration_overdue: view === "overdue" ? true : undefined,
          limit: PAGE,
          offset,
        },
        signal,
      ),
    [debounced, category, view, offset],
  );

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("offset");
    setParams(next);
  };

  return (
    <>
      <PageHeader
        title="Equipment"
        subtitle={
          items.data
            ? `${items.data.total.toLocaleString()} item${items.data.total === 1 ? "" : "s"}`
            : "The kit, and where it has gone"
        }
        actions={
          <>
            <Link className="btn" to="/inventory/out">
              What is out
            </Link>
            {can("inventory", "contributor") && (
              <Link className="btn btn-primary" to="/inventory/equipment/new">
                Add equipment
              </Link>
            )}
          </>
        }
      />

      <div className="toolbar">
        <SearchInput
          value={term}
          onChange={setTerm}
          placeholder="Asset number, name, serial number…"
        />
        <select
          className="input input-sm filter-select"
          value={category}
          onChange={(event) => setParam("category", event.target.value)}
        >
          <option value="">All categories</option>
          {categories.data?.map((name) => (
            <option key={name} value={name}>
              {humanise(name)}
            </option>
          ))}
        </select>
        <div className="row-tight">
          {[
            ["all", "All"],
            ["available", "Available"],
            ["overdue", "Calibration overdue"],
          ].map(([key, label]) => (
            <button
              key={key}
              type="button"
              className={`btn btn-sm${view === key ? " btn-primary" : ""}`}
              onClick={() => setParam("view", key === "all" ? "" : (key as string))}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {items.loading ? (
        <Loading />
      ) : items.error ? (
        <ErrorNote message={items.error} onRetry={items.reload} />
      ) : items.data && items.data.items.length === 0 ? (
        <Empty title="Nothing here yet">
          {view === "all"
            ? "Add the first piece of kit, or clear the filter."
            : "Nothing matches that filter."}
        </Empty>
      ) : (
        <section className="card">
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Asset no.</th>
                  <th>Name</th>
                  <th>Category</th>
                  <th>Status</th>
                  <th>Calibration</th>
                </tr>
              </thead>
              <tbody>
                {items.data?.items.map((item) => (
                  <tr key={item.id}>
                    <td className="mono">
                      <Link to={`/inventory/equipment/${item.id}`}>{item.asset_number}</Link>
                    </td>
                    <td>{item.name}</td>
                    <td className="small muted">
                      {item.category ? humanise(item.category) : "—"}
                    </td>
                    <td>
                      <Badge value={item.status} kind="status" />
                    </td>
                    <td className="small">
                      <CalibrationCell item={item} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {items.data && (
            <Pager
              total={items.data.total}
              limit={PAGE}
              offset={offset}
              onChange={(next) => {
                const params2 = new URLSearchParams(params);
                params2.set("offset", String(next));
                setParams(params2);
              }}
            />
          )}
        </section>
      )}
    </>
  );
}

/** Due, overdue, or not applicable — said in words rather than a bare date. */
function CalibrationCell({ item }: { item: Equipment }) {
  if (!item.needs_calibration) return <span className="muted">Not required</span>;
  if (!item.calibration_due_on) return <span className="muted">Never recorded</span>;

  const overdue = item.calibration_due_on < new Date().toISOString().slice(0, 10);
  return overdue ? (
    <Badge value="missing" kind="status" label={`Overdue since ${formatDate(item.calibration_due_on)}`} />
  ) : (
    <span>Due {formatDate(item.calibration_due_on)}</span>
  );
}

/* --------------------------------------------------------------------------
 * One item
 * ----------------------------------------------------------------------- */
export function EquipmentDetailScreen() {
  const { equipmentId } = useParams();
  const { can } = useSession();
  const [confirming, setConfirming] = useState(false);
  const [issuing, setIssuing] = useState(false);

  const item = useQuery<EquipmentDetail>(
    (signal) => api.get(`/inventory/equipment/${equipmentId}`, undefined, signal),
    [equipmentId],
  );
  const history = useQuery<Page<Checkout>>(
    (signal) => api.get(`/inventory/equipment/${equipmentId}/checkouts`, undefined, signal),
    [equipmentId],
  );
  const calibrations = useQuery<Page<Calibration>>(
    (signal) => api.get(`/inventory/equipment/${equipmentId}/calibrations`, undefined, signal),
    [equipmentId],
  );

  const bringBack = useAction(async () => {
    if (!item.data?.open_checkout) return;
    await api.post(`/inventory/checkouts/${item.data.open_checkout.id}/return`, {});
    item.reload();
    history.reload();
  });

  const remove = useAction(async () => {
    await api.delete(`/inventory/equipment/${equipmentId}`);
    window.location.href = "/inventory/equipment";
  });

  if (item.loading) return <Loading rows={8} />;
  if (item.error) return <ErrorNote message={item.error} onRetry={item.reload} />;
  if (!item.data) return null;

  const record = item.data;
  const out = record.open_checkout;

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Equipment", to: "/inventory/equipment" }, { label: record.asset_number }]}
        title={record.name}
        subtitle={<span className="mono">{record.asset_number}</span>}
        actions={
          <>
            <Badge value={record.status} kind="status" />
            {can("inventory", "contributor") &&
              (out ? (
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={bringBack.running}
                  onClick={() => void bringBack.run()}
                >
                  {bringBack.running ? "Recording…" : "Bring it back"}
                </button>
              ) : (
                <button type="button" className="btn btn-primary" onClick={() => setIssuing(true)}>
                  Take it out
                </button>
              ))}
            {record.can_delete && (
              <button type="button" className="btn btn-danger" onClick={() => setConfirming(true)}>
                Delete
              </button>
            )}
          </>
        }
      />

      {bringBack.error && <ErrorNote message={bringBack.error} />}
      {remove.error && <ErrorNote message={remove.error} />}

      {out && (
        <div className="alert alert-info" style={{ marginBottom: "var(--space-4)" }}>
          <div>
            <b>{out.borrower_label}</b> has this
            {out.destination ? ` — ${out.destination}` : ""}. Taken{" "}
            {formatDate(out.taken_at)}
            {out.due_on ? `, due back ${formatDate(out.due_on)}` : ", with no date to come back"}.
          </div>
        </div>
      )}

      {record.calibration_overdue && (
        <div className="alert alert-warning" style={{ marginBottom: "var(--space-4)" }}>
          <div>
            <b>Calibration ran out on {formatDate(record.calibration_due_on)}.</b> Readings taken
            with it after that date may be queried.
          </div>
        </div>
      )}

      <section className="card">
        <div className="card-header">
          <span className="card-title">The item</span>
        </div>
        <div className="card-body">
          <DetailGrid>
            <Detail label="Category" value={record.category ? humanise(record.category) : null} />
            <Detail label="Manufacturer" value={record.manufacturer} />
            <Detail label="Model" value={record.model} />
            <Detail label="Serial no." value={<span className="mono">{record.serial_number ?? "—"}</span>} />
            <Detail label="Home shelf" value={record.storage_path} />
            <Detail label="Condition" value={record.condition_notes as string | null} />
          </DetailGrid>
        </div>
      </section>

      <section className="card">
        <div className="card-header">
          <span className="card-title">Who has had it</span>
        </div>
        {history.data && history.data.items.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Borrower</th>
                  <th>Where</th>
                  <th>Out</th>
                  <th>Due</th>
                  <th>Back</th>
                </tr>
              </thead>
              <tbody>
                {history.data.items.map((entry) => (
                  <tr key={entry.id}>
                    <td>{entry.borrower_label}</td>
                    <td className="small muted">{entry.destination ?? "—"}</td>
                    <td className="small">{formatDate(entry.taken_at)}</td>
                    <td className="small">{entry.due_on ? formatDate(entry.due_on) : "—"}</td>
                    <td className="small">
                      {entry.returned_at ? (
                        formatDate(entry.returned_at)
                      ) : (
                        <Badge value="on_loan" kind="status" label="Still out" />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="card-body">
            <p className="small muted">It has never left the building.</p>
          </div>
        )}
      </section>

      {record.needs_calibration && (
        <section className="card">
          <div className="card-header">
            <span className="card-title">Calibration</span>
          </div>
          {calibrations.data && calibrations.data.items.length > 0 ? (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Performed</th>
                    <th>By</th>
                    <th>Certificate</th>
                    <th>Result</th>
                    <th>Next due</th>
                  </tr>
                </thead>
                <tbody>
                  {calibrations.data.items.map((entry) => (
                    <tr key={entry.id}>
                      <td className="small">{formatDate(entry.performed_on)}</td>
                      <td className="small">{entry.performed_by ?? "—"}</td>
                      <td className="small mono">{entry.certificate_number ?? "—"}</td>
                      <td>
                        <Badge
                          value={entry.result === "passed" ? "active" : entry.result === "failed" ? "missing" : "temporary"}
                          kind="status"
                          label={humanise(entry.result)}
                        />
                      </td>
                      <td className="small">
                        {entry.next_due_on ? formatDate(entry.next_due_on) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="card-body">
              <p className="small muted">
                No certificate on file. Until one is recorded, nothing can say whether this item is
                in date.
              </p>
            </div>
          )}
        </section>
      )}

      {issuing && (
        <IssueDialog
          item={record}
          onClose={() => setIssuing(false)}
          onDone={() => {
            setIssuing(false);
            item.reload();
            history.reload();
          }}
        />
      )}

      {confirming && (
        <ConfirmDelete
          name={record.asset_number}
          busy={remove.running}
          consequences="Its loan history and calibration certificates go with it. Retiring it keeps both."
          onCancel={() => setConfirming(false)}
          onConfirm={() => void remove.run()}
        />
      )}
    </>
  );
}

/** Taking an item out. A borrower is required — that is the whole point. */
function IssueDialog({
  item,
  onClose,
  onDone,
}: {
  item: EquipmentDetail;
  onClose: () => void;
  onDone: () => void;
}) {
  const [borrower, setBorrower] = useState("");
  const [destination, setDestination] = useState("");
  const [dueOn, setDueOn] = useState("");

  const issue = useAction(async () => {
    await api.post(`/inventory/equipment/${item.id}/checkouts`, {
      borrower_label: borrower.trim(),
      destination: destination.trim() || null,
      due_on: dueOn || null,
    });
    onDone();
  });

  return (
    <div className="modal-scrim" role="dialog" aria-modal="true" aria-label="Take it out">
      <div className="modal">
        <div className="modal-title">Take out {item.asset_number}</div>
        {issue.error && <ErrorNote message={issue.error} />}
        <div className="field">
          <label className="field-label" htmlFor="borrower">
            Who is taking it
          </label>
          <input
            id="borrower"
            className="input"
            value={borrower}
            autoFocus
            onChange={(event) => setBorrower(event.target.value)}
          />
          <p className="field-help">
            A name, whether or not they have an account. Field kit goes out with volunteers and
            visiting specialists who will never sign in.
          </p>
        </div>
        <div className="field">
          <label className="field-label" htmlFor="destination">
            Where it is going
          </label>
          <input
            id="destination"
            className="input"
            value={destination}
            placeholder="Trench 4"
            onChange={(event) => setDestination(event.target.value)}
          />
        </div>
        <div className="field">
          <label className="field-label" htmlFor="due">
            Back by
          </label>
          <input
            id="due"
            className="input"
            type="date"
            value={dueOn}
            onChange={(event) => setDueOn(event.target.value)}
          />
          <p className="field-help">Optional. Without one it never appears on the overdue list.</p>
        </div>
        <div className="row-tight" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn" onClick={onClose} disabled={issue.running}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={issue.running || !borrower.trim()}
            onClick={() => void issue.run()}
          >
            {issue.running ? "Recording…" : "Take it out"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ==========================================================================
 * What is out
 * ======================================================================= */
export function OutOnLoan() {
  const [overdueOnly, setOverdueOnly] = useState(false);
  const out = useQuery<Page<Checkout>>(
    (signal) =>
      api.get("/inventory/equipment/out", { overdue_only: overdueOnly || undefined }, signal),
    [overdueOnly],
  );

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Equipment", to: "/inventory/equipment" }, { label: "Out" }]}
        title="What is out of the building"
        subtitle={
          out.data
            ? `${out.data.total} item${out.data.total === 1 ? "" : "s"} on loan`
            : "Open loans, oldest first"
        }
        actions={
          <button
            type="button"
            className={`btn${overdueOnly ? " btn-primary" : ""}`}
            onClick={() => setOverdueOnly((on) => !on)}
          >
            Overdue only
          </button>
        }
      />

      {out.loading ? (
        <Loading />
      ) : out.error ? (
        <ErrorNote message={out.error} onRetry={out.reload} />
      ) : out.data && out.data.items.length === 0 ? (
        <Empty title={overdueOnly ? "Nothing is overdue" : "Everything is in"}>
          {overdueOnly
            ? "Every loan with a date on it is inside it."
            : "No equipment is out of the building."}
        </Empty>
      ) : (
        <section className="card">
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Asset no.</th>
                  <th>Item</th>
                  <th>Who has it</th>
                  <th>Where</th>
                  <th>Out since</th>
                  <th>Due</th>
                </tr>
              </thead>
              <tbody>
                {out.data?.items.map((entry) => (
                  <tr key={entry.id}>
                    <td className="mono">
                      <Link to={`/inventory/equipment/${entry.equipment_id}`}>
                        {entry.asset_number}
                      </Link>
                    </td>
                    <td>{entry.equipment_name}</td>
                    <td>{entry.borrower_label}</td>
                    <td className="small muted">{entry.destination ?? "—"}</td>
                    <td className="small">{formatDate(entry.taken_at)}</td>
                    <td className="small">
                      {entry.days_overdue ? (
                        <Badge
                          value="missing"
                          kind="status"
                          label={`${entry.days_overdue} day${entry.days_overdue === 1 ? "" : "s"} over`}
                        />
                      ) : entry.due_on ? (
                        formatDate(entry.due_on)
                      ) : (
                        <span className="muted">No date</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}

/* ==========================================================================
 * Stock
 * ======================================================================= */
export function StockList() {
  const { can } = useSession();
  const [params, setParams] = useSearchParams();
  const [term, setTerm] = useState(params.get("q") ?? "");
  const debounced = useDebounced(term);
  const lowOnly = params.get("low") === "1";
  const offset = Number(params.get("offset") ?? 0);

  const stock = useQuery<Page<Consumable>>(
    (signal) =>
      api.get(
        "/inventory/consumables",
        {
          q: debounced || undefined,
          needs_reorder: lowOnly || undefined,
          limit: PAGE,
          offset,
        },
        signal,
      ),
    [debounced, lowOnly, offset],
  );

  return (
    <>
      <PageHeader
        title="Stock"
        subtitle={
          stock.data
            ? `${stock.data.total} line${stock.data.total === 1 ? "" : "s"}`
            : "What is on the shelf"
        }
        actions={
          can("inventory", "contributor") && (
            <Link className="btn btn-primary" to="/inventory/stock/new">
              Add a stock line
            </Link>
          )
        }
      />

      <div className="toolbar">
        <SearchInput value={term} onChange={setTerm} placeholder="Code, name…" />
        <button
          type="button"
          className={`btn btn-sm${lowOnly ? " btn-primary" : ""}`}
          onClick={() => {
            const next = new URLSearchParams(params);
            if (lowOnly) next.delete("low");
            else next.set("low", "1");
            next.delete("offset");
            setParams(next);
          }}
        >
          Needs reordering
        </button>
      </div>

      {stock.loading ? (
        <Loading />
      ) : stock.error ? (
        <ErrorNote message={stock.error} onRetry={stock.reload} />
      ) : stock.data && stock.data.items.length === 0 ? (
        <Empty title={lowOnly ? "Nothing is running low" : "No stock lines yet"}>
          {lowOnly
            ? "Every line is above its reorder level."
            : "Add the things that get used up: bags, labels, permatrace, batteries."}
        </Empty>
      ) : (
        <section className="card">
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Name</th>
                  <th className="numeric">In stock</th>
                  <th className="numeric">Reorder at</th>
                  <th>Where</th>
                </tr>
              </thead>
              <tbody>
                {stock.data?.items.map((line) => {
                  const low =
                    line.reorder_level != null && Number(line.quantity) <= Number(line.reorder_level);
                  return (
                    <tr key={line.id}>
                      <td className="mono">
                        <Link to={`/inventory/stock/${line.id}`}>{line.code}</Link>
                      </td>
                      <td>{line.name}</td>
                      <td className="numeric">
                        {low ? (
                          <Badge
                            value="on_loan"
                            kind="status"
                            label={`${amount(line.quantity)} ${line.unit}`}
                          />
                        ) : (
                          <span>
                            {amount(line.quantity)} <span className="muted">{line.unit}</span>
                          </span>
                        )}
                      </td>
                      <td className="numeric small muted">
                        {line.reorder_level != null ? amount(line.reorder_level) : "—"}
                      </td>
                      <td className="small muted">
                        {line.expires_on ? `Expires ${formatDate(line.expires_on)}` : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {stock.data && (
            <Pager
              total={stock.data.total}
              limit={PAGE}
              offset={offset}
              onChange={(next) => {
                const params2 = new URLSearchParams(params);
                params2.set("offset", String(next));
                setParams(params2);
              }}
            />
          )}
        </section>
      )}
    </>
  );
}

/* --------------------------------------------------------------------------
 * One stock line, and its ledger
 * ----------------------------------------------------------------------- */
export function StockDetail() {
  const { consumableId } = useParams();
  const { can } = useSession();
  const [change, setChange] = useState("");
  const [reason, setReason] = useState("issued");
  const [issuedTo, setIssuedTo] = useState("");

  const line = useQuery<ConsumableDetail>(
    (signal) => api.get(`/inventory/consumables/${consumableId}`, undefined, signal),
    [consumableId],
  );
  const ledger = useQuery<Page<StockMovement>>(
    (signal) => api.get(`/inventory/consumables/${consumableId}/movements`, undefined, signal),
    [consumableId],
  );

  const record = useAction(async () => {
    const size = Number(change);
    if (!Number.isFinite(size) || size === 0) return;
    // Out is negative. The form asks for a plain number and a direction,
    // because "-120" typed into a box is easy to get the wrong way round.
    const signed = reason === "received" || reason === "returned" ? Math.abs(size) : -Math.abs(size);
    await api.post(`/inventory/consumables/${consumableId}/movements`, {
      change: signed,
      reason,
      issued_to_label: issuedTo.trim() || null,
    });
    setChange("");
    setIssuedTo("");
    line.reload();
    ledger.reload();
  });

  if (line.loading) return <Loading rows={8} />;
  if (line.error) return <ErrorNote message={line.error} onRetry={line.reload} />;
  if (!line.data) return null;

  const stock = line.data;

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Stock", to: "/inventory/stock" }, { label: stock.code }]}
        title={stock.name}
        subtitle={<span className="mono">{stock.code}</span>}
      />

      {stock.needs_reorder && (
        <div className="alert alert-warning" style={{ marginBottom: "var(--space-4)" }}>
          <div>
            <b>
              {amount(stock.quantity)} {stock.unit} left
            </b>
            , at or below the reorder level of {amount(stock.reorder_level)}.
          </div>
        </div>
      )}
      {stock.expired && (
        <div className="alert alert-danger" style={{ marginBottom: "var(--space-4)" }}>
          <div>
            <b>Expired {formatDate(stock.expires_on)}.</b> Do not use it on anything that matters.
          </div>
        </div>
      )}

      <section className="card">
        <div className="card-body">
          <DetailGrid>
            <Detail
              label="In stock"
              value={`${amount(stock.quantity)} ${stock.unit}`}
            />
            <Detail
              label="Reorder at"
              value={stock.reorder_level != null ? amount(stock.reorder_level) : null}
            />
            <Detail label="Kept in" value={stock.storage_path} />
            <Detail label="Supplier" value={stock.supplier as string | null} />
            <Detail
              label="Their reference"
              value={<span className="mono">{(stock.supplier_reference as string | null) ?? "—"}</span>}
            />
            <Detail label="Expires" value={stock.expires_on ? formatDate(stock.expires_on) : null} />
          </DetailGrid>
        </div>
      </section>

      {can("inventory", "contributor") && (
        <section className="card">
          <div className="card-header">
            <span className="card-title">Record a movement</span>
          </div>
          <div className="card-body">
            <p className="small muted" style={{ marginBottom: 10 }}>
              The total is the sum of this ledger, so it is never typed directly. If the count on
              the shelf disagrees with the record, that is a stock-take, and the difference goes in
              here as its own event rather than quietly changing the number.
            </p>
            {record.error && <ErrorNote message={record.error} />}
            <div className="toolbar" style={{ marginBottom: 0 }}>
              <select
                className="input input-sm filter-select"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              >
                <option value="issued">Issued</option>
                <option value="used">Used</option>
                <option value="damaged">Damaged</option>
                <option value="expired">Expired</option>
                <option value="received">Received</option>
                <option value="returned">Returned unused</option>
              </select>
              <input
                className="input input-sm"
                style={{ width: 120 }}
                inputMode="decimal"
                placeholder={`How many ${stock.unit}`}
                value={change}
                onChange={(event) => setChange(event.target.value)}
              />
              <input
                className="input input-sm"
                style={{ maxWidth: 220 }}
                placeholder="Who or what for"
                value={issuedTo}
                onChange={(event) => setIssuedTo(event.target.value)}
              />
              <button
                type="button"
                className="btn btn-sm btn-primary"
                disabled={record.running || !change.trim()}
                onClick={() => void record.run()}
              >
                {record.running ? "Recording…" : "Record"}
              </button>
            </div>
          </div>
        </section>
      )}

      <section className="card">
        <div className="card-header">
          <span className="card-title">The ledger</span>
        </div>
        {ledger.data && ledger.data.items.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>When</th>
                  <th className="numeric">Change</th>
                  <th className="numeric">Left</th>
                  <th>Why</th>
                  <th>Who</th>
                </tr>
              </thead>
              <tbody>
                {ledger.data.items.map((entry) => (
                  <tr key={entry.id}>
                    <td className="small">{formatDateTime(entry.occurred_at)}</td>
                    <td
                      className="numeric mono"
                      style={{ color: Number(entry.change) < 0 ? "var(--danger)" : "var(--ok)" }}
                    >
                      {Number(entry.change) > 0 ? "+" : ""}
                      {amount(entry.change)}
                    </td>
                    <td className="numeric mono">{amount(entry.balance_after)}</td>
                    <td className="small">{humanise(entry.reason)}</td>
                    <td className="small muted">
                      {entry.issued_to_label ?? entry.recorded_by_label ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="card-body">
            <p className="small muted">Nothing has moved yet.</p>
          </div>
        )}
      </section>
    </>
  );
}

/* ==========================================================================
 * Packing lists
 * ======================================================================= */
export function KitTemplates() {
  const templates = useQuery<Page<KitTemplate>>(
    (signal) => api.get("/inventory/kit-templates", { limit: 100 }, signal),
    [],
  );

  return (
    <>
      <PageHeader
        title="Packing lists"
        subtitle="What a kind of day's work needs"
        actions={
          <Link className="btn" to="/inventory/kits">
            Kits that have gone out
          </Link>
        }
      />

      {templates.loading ? (
        <Loading />
      ) : templates.error ? (
        <ErrorNote message={templates.error} onRetry={templates.reload} />
      ) : templates.data && templates.data.items.length === 0 ? (
        <Empty title="No packing lists yet">
          A packing list is written once by somebody who knows what gets forgotten, and used by
          whoever is loading the van at six in the morning.
        </Empty>
      ) : (
        <div className="stat-grid">
          {templates.data?.items.map((template) => (
            <Link key={template.id} className="stat" to={`/inventory/kit-templates/${template.id}`}>
              <span className="stat-label">{template.name}</span>
              <span className="stat-value">{template.line_count}</span>
              <span className="small muted">
                {template.line_count === 1 ? "line" : "lines"}
                {template.description ? ` · ${template.description}` : ""}
              </span>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}

export function KitTemplateScreen() {
  const { templateId } = useParams();
  const { can } = useSession();
  const [building, setBuilding] = useState(false);

  const template = useQuery<KitTemplateDetail>(
    (signal) => api.get(`/inventory/kit-templates/${templateId}`, undefined, signal),
    [templateId],
  );

  if (template.loading) return <Loading rows={6} />;
  if (template.error) return <ErrorNote message={template.error} onRetry={template.reload} />;
  if (!template.data) return null;

  const list = template.data;

  return (
    <>
      <PageHeader
        breadcrumb={[
          { label: "Packing lists", to: "/inventory/kit-templates" },
          { label: list.name },
        ]}
        title={list.name}
        subtitle={list.description}
        actions={
          can("inventory", "contributor") && (
            <button type="button" className="btn btn-primary" onClick={() => setBuilding(true)}>
              Build this kit
            </button>
          )
        }
      />

      <section className="card">
        <div className="card-header">
          <span className="card-title">On the list</span>
        </div>
        <ul className="plan-contents" style={{ padding: "var(--space-4)" }}>
          {list.lines.map((line) => (
            <li key={line.id}>
              <span className="mono small muted">{line.position + 1}</span>
              <span>{line.label}</span>
              {line.is_optional && <span className="badge badge-warning">Optional</span>}
            </li>
          ))}
        </ul>
      </section>

      {building && (
        <BuildDialog
          template={list}
          onClose={() => setBuilding(false)}
        />
      )}
    </>
  );
}

function BuildDialog({ template, onClose }: { template: KitTemplateDetail; onClose: () => void }) {
  const [issuedTo, setIssuedTo] = useState("");
  const [destination, setDestination] = useState("");
  const [dueOn, setDueOn] = useState("");
  const [allOrNothing, setAllOrNothing] = useState(false);
  const [built, setBuilt] = useState<KitDetail | null>(null);

  const build = useAction(async () => {
    const kit = await api.post<KitDetail>(`/inventory/kit-templates/${template.id}/build`, {
      issued_to_label: issuedTo.trim(),
      destination: destination.trim() || null,
      due_on: dueOn || null,
      all_or_nothing: allOrNothing,
    });
    setBuilt(kit);
  });

  if (built) {
    return (
      <div className="modal-scrim" role="dialog" aria-modal="true" aria-label="Kit built">
        <div className="modal" style={{ maxWidth: 560 }}>
          <div className="modal-title">{built.name}</div>
          <KitContents kit={built} />
          <div className="row-tight" style={{ justifyContent: "flex-end", marginTop: 14 }}>
            <Link className="btn btn-primary" to={`/inventory/kits/${built.id}`}>
              Open the kit
            </Link>
            <button type="button" className="btn" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="modal-scrim" role="dialog" aria-modal="true" aria-label="Build this kit">
      <div className="modal">
        <div className="modal-title">Build {template.name}</div>
        {build.error && <ErrorNote message={build.error} />}
        <div className="field">
          <label className="field-label" htmlFor="issued-to">
            Who is taking it
          </label>
          <input
            id="issued-to"
            className="input"
            value={issuedTo}
            autoFocus
            onChange={(event) => setIssuedTo(event.target.value)}
          />
        </div>
        <div className="field">
          <label className="field-label" htmlFor="kit-destination">
            Where it is going
          </label>
          <input
            id="kit-destination"
            className="input"
            placeholder="Trench 4"
            value={destination}
            onChange={(event) => setDestination(event.target.value)}
          />
        </div>
        <div className="field">
          <label className="field-label" htmlFor="kit-due">
            Back by
          </label>
          <input
            id="kit-due"
            className="input"
            type="date"
            value={dueOn}
            onChange={(event) => setDueOn(event.target.value)}
          />
        </div>
        <label className="checkbox small" style={{ marginBottom: 14 }}>
          <input
            type="checkbox"
            checked={allOrNothing}
            onChange={(event) => setAllOrNothing(event.target.checked)}
          />
          Refuse the whole kit unless everything on the list is available
        </label>
        <p className="small muted" style={{ marginBottom: 14 }}>
          Left unticked, the store hands over what it has and tells you what is missing — which is
          usually what you want at six in the morning.
        </p>
        <div className="row-tight" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn" onClick={onClose} disabled={build.running}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={build.running || !issuedTo.trim()}
            onClick={() => void build.run()}
          >
            {build.running ? "Building…" : "Build it"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ==========================================================================
 * Kits
 * ======================================================================= */
export function Kits() {
  const [openOnly, setOpenOnly] = useState(true);
  const kits = useQuery<Page<Kit>>(
    (signal) => api.get("/inventory/kits", { open_only: openOnly || undefined }, signal),
    [openOnly],
  );

  return (
    <>
      <PageHeader
        title="Kits"
        subtitle="What has gone out, and what it was short of"
        actions={
          <>
            <Link className="btn" to="/inventory/kit-templates">
              Packing lists
            </Link>
            <button
              type="button"
              className={`btn${openOnly ? " btn-primary" : ""}`}
              onClick={() => setOpenOnly((on) => !on)}
            >
              Still out
            </button>
          </>
        }
      />

      {kits.loading ? (
        <Loading />
      ) : kits.error ? (
        <ErrorNote message={kits.error} onRetry={kits.reload} />
      ) : kits.data && kits.data.items.length === 0 ? (
        <Empty title={openOnly ? "Nothing is out" : "No kits yet"}>
          {openOnly
            ? "Every kit has come back."
            : "Build one from a packing list to see it here."}
        </Empty>
      ) : (
        <section className="card">
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Kit</th>
                  <th>Who has it</th>
                  <th>Where</th>
                  <th>Out</th>
                  <th>Due</th>
                  <th>Back</th>
                </tr>
              </thead>
              <tbody>
                {kits.data?.items.map((kit) => (
                  <tr key={kit.id}>
                    <td>
                      <Link to={`/inventory/kits/${kit.id}`}>{kit.name}</Link>
                    </td>
                    <td>{kit.issued_to_label}</td>
                    <td className="small muted">{kit.destination ?? "—"}</td>
                    <td className="small">{formatDate(kit.issued_at)}</td>
                    <td className="small">{kit.due_on ? formatDate(kit.due_on) : "—"}</td>
                    <td className="small">
                      {kit.returned_at ? (
                        formatDate(kit.returned_at)
                      ) : (
                        <Badge value="on_loan" kind="status" label="Still out" />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}

export function KitScreen() {
  const { kitId } = useParams();
  const { can } = useSession();

  const kit = useQuery<KitDetail>(
    (signal) => api.get(`/inventory/kits/${kitId}`, undefined, signal),
    [kitId],
  );

  const bringBack = useAction(async () => {
    await api.post(`/inventory/kits/${kitId}/return`, {});
    kit.reload();
  });

  if (kit.loading) return <Loading rows={6} />;
  if (kit.error) return <ErrorNote message={kit.error} onRetry={kit.reload} />;
  if (!kit.data) return null;

  const record = kit.data;

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Kits", to: "/inventory/kits" }, { label: record.name }]}
        title={record.name}
        subtitle={`${record.issued_to_label}${record.destination ? ` — ${record.destination}` : ""}`}
        actions={
          can("inventory", "contributor") &&
          !record.returned_at && (
            <button
              type="button"
              className="btn btn-primary"
              disabled={bringBack.running}
              onClick={() => void bringBack.run()}
            >
              {bringBack.running ? "Recording…" : "Bring it all back"}
            </button>
          )
        }
      />

      {bringBack.error && <ErrorNote message={bringBack.error} />}

      <section className="card">
        <div className="card-body">
          <KitContents kit={record} />
        </div>
      </section>
    </>
  );
}

/** The contents of a kit, and what it could not supply. */
function KitContents({ kit }: { kit: KitDetail }) {
  const required = useMemo(
    () => kit.shortfalls.filter((entry) => !entry.is_optional),
    [kit.shortfalls],
  );

  return (
    <>
      {kit.shortfalls.length > 0 && (
        <div
          className={`alert ${required.length ? "alert-warning" : "alert-info"}`}
          style={{ marginBottom: "var(--space-4)" }}
        >
          <div>
            <b>
              {kit.shortfalls.length} thing{kit.shortfalls.length === 1 ? "" : "s"} the store could
              not supply
            </b>
            <ul style={{ margin: "6px 0 0 18px" }}>
              {kit.shortfalls.map((entry, index) => (
                <li key={`${entry.what}-${index}`} className="small">
                  {entry.what} — {entry.reason}
                  {entry.supplied > 0 && ` (${entry.supplied} of ${entry.wanted} went out)`}
                  {entry.is_optional && " · optional"}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {kit.checkouts.length > 0 && (
        <>
          <div className="field-label" style={{ marginBottom: 6 }}>
            Equipment
          </div>
          <ul className="plan-contents" style={{ marginBottom: 14 }}>
            {kit.checkouts.map((entry) => (
              <li key={entry.id}>
                <span className="mono small">{entry.asset_number}</span>
                <span>{entry.equipment_name}</span>
                {entry.returned_at ? (
                  <span className="badge">Back</span>
                ) : (
                  <Badge value="on_loan" kind="status" label="Out" />
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      {kit.stock_movements.length > 0 && (
        <>
          <div className="field-label" style={{ marginBottom: 6 }}>
            Consumables issued
          </div>
          <ul className="plan-contents">
            {kit.stock_movements.map((entry) => (
              <li key={entry.id}>
                <span className="mono small">
                  {amount(Math.abs(Number(entry.change)))} {entry.unit ?? ""}
                </span>
                <span>{entry.consumable_name ?? entry.consumable_code ?? "—"}</span>
              </li>
            ))}
          </ul>
        </>
      )}

      {kit.checkouts.length === 0 && kit.stock_movements.length === 0 && (
        <p className="small muted">The store could supply nothing on this list.</p>
      )}
    </>
  );
}


/* ==========================================================================
 * Adding things
 *
 * Both forms are the layout the backend serves, rendered. Nothing here knows
 * what fields a piece of equipment has — which is the point: adding a field to
 * the layout puts it on this screen with no frontend change at all.
 * ======================================================================= */
function NewRecord({
  recordType,
  title,
  subtitle,
  endpoint,
  backTo,
  backLabel,
  detailPath,
}: {
  recordType: string;
  title: string;
  subtitle: string;
  endpoint: string;
  backTo: string;
  backLabel: string;
  detailPath: (id: string) => string;
}) {
  const navigate = useNavigate();
  const [values, setValues] = useState<RecordValues>({});
  const layout = useQuery<FormLayout>(
    (signal) => api.get(`/forms/layouts/${recordType}`, undefined, signal),
    [recordType],
  );

  const create = useAction(async () => {
    const known = writableKeys(layout.data!);
    const payload: RecordValues = {};
    for (const [key, value] of Object.entries(values)) {
      if (known.has(key) && value !== null && value !== undefined && value !== "") {
        payload[key] = value;
      }
    }
    const created = await api.post<{ id: string }>(endpoint, payload);
    navigate(detailPath(created.id));
  });

  if (layout.loading) return <Loading rows={8} />;
  if (layout.error || !layout.data) {
    return <ErrorNote message={layout.error ?? "No layout"} onRetry={layout.reload} />;
  }

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: backLabel, to: backTo }, { label: title }]}
        title={title}
        subtitle={subtitle}
        actions={
          <>
            <button type="button" className="btn" onClick={() => navigate(backTo)}>
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

export function NewEquipment() {
  return (
    <NewRecord
      recordType="equipment"
      title="Add equipment"
      subtitle="The asset number is what somebody reads off the case when they ring up."
      endpoint="/inventory/equipment"
      backTo="/inventory/equipment"
      backLabel="Equipment"
      detailPath={(id) => `/inventory/equipment/${id}`}
    />
  );
}

export function NewStockLine() {
  return (
    <NewRecord
      recordType="consumable"
      title="Add a stock line"
      subtitle="What is on the shelf now goes in as an opening count, so the ledger starts where the stock does."
      endpoint="/inventory/consumables"
      backTo="/inventory/stock"
      backLabel="Stock"
      detailPath={(id) => `/inventory/stock/${id}`}
    />
  );
}
