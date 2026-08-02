/**
 * Money, and the work that has to happen.
 *
 * The balance bar is the piece worth explaining. It draws three quantities,
 * not one, because "how much is left" has three answers and only one of them
 * is the useful one:
 *
 * - **Paid** — invoices that have gone out.
 * - **Committed** — ordered or contracted, not yet paid. Gone, even though it
 *   is still in the account.
 * - **Available** — the award, less both.
 *
 * Planned spending is shown *beside* the bar rather than inside it. It is a
 * forecast, and a forecast drawn as though it were spent turns "we might need
 * a second total station" into "we cannot afford one".
 */

import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import {
  api,
  type Budget,
  type BudgetDetail,
  type BudgetTotals,
  type ActivityOption,
  type CalendarEvent,
  type Expense,
  type Page,
  type Task,
  type TaskBoard,
} from "../lib/api";
import { useAction, useDebounced, useQuery, useSession } from "../lib/hooks";
import {
  Badge,
  Detail,
  DetailGrid,
  Empty,
  ErrorNote,
  Loading,
  PageHeader,
  Pager,
  SearchInput,
  formatDate,
  humanise,
} from "../components/ui";

const PAGE = 50;

/** Money, written the way it appears on an invoice. */
function money(value: number | null | undefined, currency = "USD") {
  const amount = Number(value ?? 0);
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(amount);
  } catch {
    // An unrecognised currency code should not take the screen down; a
    // three-letter code beside the number is perfectly readable.
    return `${amount.toLocaleString()} ${currency}`;
  }
}

/* ==========================================================================
 * Budgets
 * ======================================================================= */
export function Budgets() {
  const { can } = useSession();
  const [params, setParams] = useSearchParams();
  const [term, setTerm] = useState(params.get("q") ?? "");
  const debounced = useDebounced(term);
  const offset = Number(params.get("offset") ?? 0);

  const totals = useQuery<BudgetTotals>(
    (signal) => api.get("/management/budgets/totals", undefined, signal),
    [],
  );
  const budgets = useQuery<Page<Budget>>(
    (signal) =>
      api.get("/management/budgets", { q: debounced || undefined, limit: PAGE, offset }, signal),
    [debounced, offset],
  );

  const attention = new Set(totals.data?.needing_attention ?? []);

  return (
    <>
      <PageHeader
        title="Funds"
        subtitle={
          budgets.data
            ? `${budgets.data.total} fund${budgets.data.total === 1 ? "" : "s"}`
            : "Grants, allocations and contracts"
        }
        actions={
          <>
            <Link className="btn" to="/management/expenses">
              All spending
            </Link>
            {can("management", "contributor") && (
              <Link className="btn btn-primary" to="/management/budgets/new">
                Add a fund
              </Link>
            )}
          </>
        }
      />

      {totals.data && totals.data.budget_count > 0 && (
        <div className="stat-grid" style={{ marginBottom: "var(--space-5)" }}>
          <div className="stat">
            <span className="stat-label">Awarded</span>
            <span className="stat-value">{money(totals.data.total)}</span>
            <span className="small muted">
              across {totals.data.budget_count} fund
              {totals.data.budget_count === 1 ? "" : "s"}
            </span>
          </div>
          <div className="stat">
            <span className="stat-label">Spent or committed</span>
            <span className="stat-value">{money(totals.data.spent)}</span>
          </div>
          <div className="stat">
            <span className="stat-label">Available</span>
            <span className="stat-value">{money(totals.data.available)}</span>
            {Object.keys(totals.data.by_currency).length > 1 && (
              <span className="small muted">
                {Object.entries(totals.data.by_currency)
                  .map(([code, value]) => money(value, code))
                  .join(" · ")}
              </span>
            )}
          </div>
        </div>
      )}

      {Object.keys(totals.data?.by_currency ?? {}).length > 1 && (
        <div className="alert alert-info" style={{ marginBottom: "var(--space-4)" }}>
          <div>
            These funds are in more than one currency. The summed figures above add them
            together, which is only an indication — the per-currency line is the one a funder
            would recognise.
          </div>
        </div>
      )}

      <div className="toolbar">
        <SearchInput value={term} onChange={setTerm} placeholder="Code, name, funder…" />
      </div>

      {budgets.loading ? (
        <Loading />
      ) : budgets.error ? (
        <ErrorNote message={budgets.error} onRetry={budgets.reload} />
      ) : budgets.data && budgets.data.items.length === 0 ? (
        <Empty title="No funds yet">
          Add the grant or allocation that pays for the work, and spending can be charged
          against it.
        </Empty>
      ) : (
        <div className="stat-grid">
          {budgets.data?.items.map((budget) => (
            <Link
              key={budget.id}
              className="stat"
              to={`/management/budgets/${budget.id}`}
              style={{ display: "block" }}
            >
              <div className="row-tight" style={{ justifyContent: "space-between" }}>
                <span className="stat-label">{budget.code}</span>
                {budget.overspent ? (
                  <Badge value="missing" kind="status" label="Over" />
                ) : attention.has(budget.id) ? (
                  <Badge value="temporary" kind="status" label="Check" />
                ) : null}
              </div>
              <div className="strong" style={{ marginBottom: 6 }}>
                {budget.name}
              </div>
              <BalanceBar budget={budget} />
              <div className="small muted" style={{ marginTop: 6 }}>
                {money(budget.available, budget.currency)} left of{" "}
                {money(budget.amount, budget.currency)}
                {budget.ends_on ? ` · to ${formatDate(budget.ends_on)}` : ""}
              </div>
            </Link>
          ))}
        </div>
      )}

      {budgets.data && (
        <Pager
          total={budgets.data.total}
          limit={PAGE}
          offset={offset}
          onChange={(next) => {
            const params2 = new URLSearchParams(params);
            params2.set("offset", String(next));
            setParams(params2);
          }}
        />
      )}
    </>
  );
}

/**
 * Paid and committed, drawn separately.
 *
 * Never colour alone: paid is solid, committed is hatched, and both are
 * labelled underneath. Somebody who cannot tell the two shades apart still
 * gets the answer.
 */
function BalanceBar({ budget }: { budget: Budget }) {
  if (budget.amount <= 0) {
    return <div className="small muted">No amount set on this fund.</div>;
  }

  const paid = Math.min(100, (budget.paid / budget.amount) * 100);
  const committed = Math.min(100 - paid, (budget.committed / budget.amount) * 100);

  return (
    <>
      <div
        className={`balance${budget.overspent ? " over" : ""}`}
        role="img"
        aria-label={`${money(budget.paid, budget.currency)} paid, ${money(
          budget.committed,
          budget.currency,
        )} committed, of ${money(budget.amount, budget.currency)}`}
      >
        <span className="balance-paid" style={{ width: `${paid}%` }} />
        <span className="balance-committed" style={{ width: `${committed}%` }} />
      </div>
      <div className="balance-key small">
        <span>
          <i className="key-paid" /> {money(budget.paid, budget.currency)} paid
        </span>
        <span>
          <i className="key-committed" /> {money(budget.committed, budget.currency)} committed
        </span>
      </div>
    </>
  );
}

/* --------------------------------------------------------------------------
 * One fund
 * ----------------------------------------------------------------------- */
export function BudgetScreen() {
  const { budgetId } = useParams();
  const { can } = useSession();
  const [adding, setAdding] = useState(false);

  const budget = useQuery<BudgetDetail>(
    (signal) => api.get(`/management/budgets/${budgetId}`, undefined, signal),
    [budgetId],
  );
  const expenses = useQuery<Page<Expense>>(
    (signal) => api.get("/management/expenses", { budget_id: budgetId, limit: 100 }, signal),
    [budgetId],
  );

  if (budget.loading) return <Loading rows={8} />;
  if (budget.error) return <ErrorNote message={budget.error} onRetry={budget.reload} />;
  if (!budget.data) return null;

  const fund = budget.data;

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Funds", to: "/management/budgets" }, { label: fund.code }]}
        title={fund.name}
        subtitle={
          <>
            <span className="mono">{fund.code}</span>
            {fund.funder ? ` · ${fund.funder}` : ""}
          </>
        }
        actions={
          <>
            <Badge value={fund.status} kind="status" />
            {can("management", "contributor") && fund.status === "active" && (
              <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}>
                Record spending
              </button>
            )}
          </>
        }
      />

      {fund.overspent && (
        <div className="alert alert-danger" style={{ marginBottom: "var(--space-4)" }}>
          <div>
            <b>Over by {money(Math.abs(fund.available), fund.currency)}.</b> Committed and paid
            spending together exceed the award.
          </div>
        </div>
      )}
      {fund.expired_with_funds && (
        <div className="alert alert-warning" style={{ marginBottom: "var(--space-4)" }}>
          <div>
            <b>This fund ended on {formatDate(fund.ends_on)} with {money(fund.available, fund.currency)} unspent.</b>{" "}
            Unspent grant money usually has to be returned — worth checking the agreement.
          </div>
        </div>
      )}

      <section className="card">
        <div className="card-body">
          <BalanceBar budget={fund} />
          <DetailGrid>
            <Detail label="Awarded" value={money(fund.amount, fund.currency)} />
            <Detail label="Paid" value={money(fund.paid, fund.currency)} />
            <Detail label="Committed" value={money(fund.committed, fund.currency)} />
            <Detail
              label="Available"
              value={
                <span className={fund.overspent ? "strong" : undefined}>
                  {money(fund.available, fund.currency)}
                </span>
              }
            />
            <Detail
              label="Planned"
              value={
                fund.planned > 0 ? (
                  <>
                    {money(fund.planned, fund.currency)}{" "}
                    <span className="small muted">— a forecast, not yet committed</span>
                  </>
                ) : null
              }
            />
            <Detail label="Runs" value={
              fund.starts_on || fund.ends_on
                ? `${fund.starts_on ? formatDate(fund.starts_on) : "—"} to ${fund.ends_on ? formatDate(fund.ends_on) : "—"}`
                : null
            } />
            <Detail label="Project" value={fund.project_name} />
            <Detail label="Managed by" value={fund.manager_label} />
            <Detail label="Their reference" value={fund.grant_reference} />
          </DetailGrid>
        </div>
      </section>

      {fund.by_category.length > 0 && (
        <section className="card">
          <div className="card-header">
            <span className="card-title">Where it went</span>
            <span className="small muted">Paid and committed together</span>
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Category</th>
                  <th className="numeric">Amount</th>
                  <th className="numeric">Share</th>
                  <th className="numeric">Lines</th>
                </tr>
              </thead>
              <tbody>
                {fund.by_category.map((line) => (
                  <tr key={line.category}>
                    <td>{line.label}</td>
                    <td className="numeric mono">{money(line.amount, fund.currency)}</td>
                    <td className="numeric">
                      <span className="share">
                        <span className="share-fill" style={{ width: `${line.percent}%` }} />
                      </span>
                      <span className="small muted"> {line.percent}%</span>
                    </td>
                    <td className="numeric small muted">{line.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="card">
        <div className="card-header">
          <span className="card-title">Every line</span>
        </div>
        {expenses.data && expenses.data.items.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>What</th>
                  <th>Category</th>
                  <th>Status</th>
                  <th className="numeric">Amount</th>
                </tr>
              </thead>
              <tbody>
                {expenses.data.items.map((line) => (
                  <tr key={line.id}>
                    <td className="small">{formatDate(line.spent_on)}</td>
                    <td>
                      {line.description}
                      {line.supplier && <span className="small muted"> · {line.supplier}</span>}
                    </td>
                    <td className="small muted">{humanise(line.category)}</td>
                    <td>
                      <ExpenseBadge status={line.status} />
                    </td>
                    <td className="numeric mono">{money(line.amount, line.currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="card-body">
            <p className="small muted">Nothing has been charged to this fund yet.</p>
          </div>
        )}
      </section>

      {adding && (
        <SpendDialog
          budget={fund}
          onClose={() => setAdding(false)}
          onDone={() => {
            setAdding(false);
            budget.reload();
            expenses.reload();
          }}
        />
      )}
    </>
  );
}

/** Paid, committed, planned or cancelled — and each means something different. */
function ExpenseBadge({ status }: { status: string }) {
  const tone =
    status === "paid"
      ? "active"
      : status === "committed"
        ? "on_loan"
        : status === "cancelled"
          ? "archived"
          : "planned";
  return <Badge value={tone} kind="status" label={humanise(status)} />;
}

function SpendDialog({
  budget,
  onClose,
  onDone,
}: {
  budget: BudgetDetail;
  onClose: () => void;
  onDone: () => void;
}) {
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [category, setCategory] = useState("other");
  const [status, setStatus] = useState("committed");
  const [spentOn, setSpentOn] = useState(new Date().toISOString().slice(0, 10));
  const [supplier, setSupplier] = useState("");
  const [warning, setWarning] = useState<Expense | null>(null);

  const record = useAction(async () => {
    const created = await api.post<Expense>(`/management/budgets/${budget.id}/expenses`, {
      description: description.trim(),
      amount: Number(amount),
      category,
      status,
      spent_on: spentOn,
      supplier: supplier.trim() || null,
    });
    // An overspend is recorded, not refused — but it is worth stopping to say
    // so, because the alternative is somebody finding out at the year end.
    if (created.overspent_by) setWarning(created);
    else onDone();
  });

  if (warning) {
    return (
      <div className="modal-scrim" role="dialog" aria-modal="true" aria-label="Recorded, and over">
        <div className="modal">
          <div className="modal-title">Recorded — and it takes the fund over</div>
          <p className="small" style={{ margin: "8px 0 14px", color: "var(--text-2)" }}>
            <b>{budget.code}</b> is now over by{" "}
            <b>{money(Math.abs(warning.budget_available_after ?? 0), budget.currency)}</b>. The line
            was saved: a fund that is genuinely overspent should say so rather than refuse the
            record.
          </p>
          <div className="row-tight" style={{ justifyContent: "flex-end" }}>
            <button type="button" className="btn btn-primary" onClick={onDone}>
              Understood
            </button>
          </div>
        </div>
      </div>
    );
  }

  const available = budget.available;
  const wouldExceed = Number(amount) > available && status !== "planned";

  return (
    <div className="modal-scrim" role="dialog" aria-modal="true" aria-label="Record spending">
      <div className="modal">
        <div className="modal-title">Record spending against {budget.code}</div>
        {record.error && <ErrorNote message={record.error} />}

        <div className="field">
          <label className="field-label" htmlFor="what">
            What it was for
          </label>
          <input
            id="what"
            className="input"
            value={description}
            autoFocus
            onChange={(event) => setDescription(event.target.value)}
          />
        </div>

        <div className="row-tight">
          <div className="field" style={{ flex: 1 }}>
            <label className="field-label" htmlFor="amount">
              Amount ({budget.currency})
            </label>
            <input
              id="amount"
              className="input"
              inputMode="decimal"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
            />
          </div>
          <div className="field" style={{ flex: 1 }}>
            <label className="field-label" htmlFor="spent-on">
              When
            </label>
            <input
              id="spent-on"
              className="input"
              type="date"
              value={spentOn}
              onChange={(event) => setSpentOn(event.target.value)}
            />
          </div>
        </div>

        <div className="row-tight">
          <div className="field" style={{ flex: 1 }}>
            <label className="field-label" htmlFor="category">
              Category
            </label>
            <select
              id="category"
              className="input"
              value={category}
              onChange={(event) => setCategory(event.target.value)}
            >
              {[
                "fieldwork",
                "travel",
                "accommodation",
                "salaries",
                "equipment",
                "consumables",
                "analysis",
                "conservation",
                "publication",
                "permits",
                "overheads",
                "other",
              ].map((name) => (
                <option key={name} value={name}>
                  {humanise(name)}
                </option>
              ))}
            </select>
            <p className="field-help">The breakdown a funder asks for is built from this.</p>
          </div>
          <div className="field" style={{ flex: 1 }}>
            <label className="field-label" htmlFor="status">
              Stage
            </label>
            <select
              id="status"
              className="input"
              value={status}
              onChange={(event) => setStatus(event.target.value)}
            >
              <option value="planned">Planned — a forecast only</option>
              <option value="committed">Committed — ordered or invoiced</option>
              <option value="paid">Paid</option>
            </select>
            <p className="field-help">
              Planned spending does not reduce what is available. Committed does.
            </p>
          </div>
        </div>

        <div className="field">
          <label className="field-label" htmlFor="supplier">
            Supplier
          </label>
          <input
            id="supplier"
            className="input"
            value={supplier}
            onChange={(event) => setSupplier(event.target.value)}
          />
        </div>

        {wouldExceed && (
          <div className="alert alert-warning" style={{ marginBottom: 12 }}>
            <div>
              This is more than the {money(available, budget.currency)} available. It will still be
              recorded — the fund will simply show as over.
            </div>
          </div>
        )}

        <div className="row-tight" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn" onClick={onClose} disabled={record.running}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={record.running || !description.trim() || !Number(amount)}
            onClick={() => void record.run()}
          >
            {record.running ? "Recording…" : "Record"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ==========================================================================
 * All spending
 * ======================================================================= */
export function Expenses() {
  const [params, setParams] = useSearchParams();
  const [term, setTerm] = useState(params.get("q") ?? "");
  const debounced = useDebounced(term);
  const category = params.get("category") ?? "";
  const offset = Number(params.get("offset") ?? 0);

  const expenses = useQuery<Page<Expense>>(
    (signal) =>
      api.get(
        "/management/expenses",
        { q: debounced || undefined, category: category || undefined, limit: PAGE, offset },
        signal,
      ),
    [debounced, category, offset],
  );

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Funds", to: "/management/budgets" }, { label: "Spending" }]}
        title="All spending"
        subtitle="Every line, across every fund"
      />

      <div className="toolbar">
        <SearchInput value={term} onChange={setTerm} placeholder="Description, supplier, invoice…" />
        <select
          className="input input-sm filter-select"
          value={category}
          onChange={(event) => {
            const next = new URLSearchParams(params);
            if (event.target.value) next.set("category", event.target.value);
            else next.delete("category");
            next.delete("offset");
            setParams(next);
          }}
        >
          <option value="">All categories</option>
          {[
            "fieldwork",
            "travel",
            "accommodation",
            "salaries",
            "equipment",
            "consumables",
            "analysis",
            "conservation",
            "publication",
            "permits",
            "overheads",
            "other",
          ].map((name) => (
            <option key={name} value={name}>
              {humanise(name)}
            </option>
          ))}
        </select>
      </div>

      {expenses.loading ? (
        <Loading />
      ) : expenses.error ? (
        <ErrorNote message={expenses.error} onRetry={expenses.reload} />
      ) : expenses.data && expenses.data.items.length === 0 ? (
        <Empty title="Nothing recorded">No spending matches.</Empty>
      ) : (
        <section className="card">
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>What</th>
                  <th>Fund</th>
                  <th>Category</th>
                  <th>Status</th>
                  <th className="numeric">Amount</th>
                </tr>
              </thead>
              <tbody>
                {expenses.data?.items.map((line) => (
                  <tr key={line.id}>
                    <td className="small">{formatDate(line.spent_on)}</td>
                    <td>
                      {line.description}
                      {line.supplier && <span className="small muted"> · {line.supplier}</span>}
                    </td>
                    <td className="small">
                      <Link className="mono" to={`/management/budgets/${line.budget_id}`}>
                        {line.budget_code}
                      </Link>
                    </td>
                    <td className="small muted">{humanise(line.category)}</td>
                    <td>
                      <ExpenseBadge status={line.status} />
                    </td>
                    <td className="numeric mono">{money(line.amount, line.currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {expenses.data && (
            <Pager
              total={expenses.data.total}
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

/* ==========================================================================
 * Tasks
 * ======================================================================= */
export function Tasks() {
  const { can } = useSession();
  const [mine, setMine] = useState(false);
  const [title, setTitle] = useState("");

  const board = useQuery<TaskBoard>(
    (signal) => api.get("/management/tasks/board", { mine: mine || undefined }, signal),
    [mine],
  );

  const [assignee, setAssignee] = useState("");
  const [dueOn, setDueOn] = useState("");

  // Anybody signed in may be given work, so the picker lists everybody rather
  // than only people with management access. /users is readable by any account
  // for exactly this reason.
  const people = useQuery<Page<{ id: string; username: string; full_name?: string | null }>>(
    (signal) => api.get("/users", { limit: 200 }, signal),
    [],
  );

  const add = useAction(async () => {
    await api.post("/management/tasks", {
      title: title.trim(),
      assignee_id: assignee || null,
      due_on: dueOn || null,
    });
    setTitle("");
    setAssignee("");
    setDueOn("");
    board.reload();
  });

  const move = useAction(async (id: string, status: string) => {
    await api.patch(`/management/tasks/${id}`, { status });
    board.reload();
  });

  const columns: { key: keyof TaskBoard; label: string; next?: string }[] = [
    { key: "todo", label: "To do", next: "in_progress" },
    { key: "in_progress", label: "In progress", next: "done" },
    { key: "blocked", label: "Blocked", next: "in_progress" },
    { key: "done", label: "Done" },
  ];

  return (
    <>
      <PageHeader
        title="Tasks"
        subtitle={
          board.data?.overdue_count
            ? `${board.data.overdue_count} overdue`
            : "What still has to happen"
        }
        actions={
          <button
            type="button"
            className={`btn${mine ? " btn-primary" : ""}`}
            onClick={() => setMine((on) => !on)}
          >
            Mine only
          </button>
        }
      />

      {can("management", "contributor") && (
        <div className="toolbar">
          <input
            className="input"
            style={{ maxWidth: 460 }}
            placeholder="Add a task and press Enter…"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && title.trim()) void add.run();
            }}
          />
          <select
            className="input input-sm filter-select"
            value={assignee}
            onChange={(event) => setAssignee(event.target.value)}
            aria-label="Who is doing it"
          >
            <option value="">Nobody yet</option>
            {people.data?.items.map((person) => (
              <option key={person.id} value={person.id}>
                {person.full_name || person.username}
              </option>
            ))}
          </select>
          <input
            className="input input-sm"
            type="date"
            value={dueOn}
            onChange={(event) => setDueOn(event.target.value)}
            aria-label="When it is due"
            style={{ maxWidth: 170 }}
          />
          <button
            type="button"
            className="btn btn-sm"
            disabled={add.running || !title.trim()}
            onClick={() => void add.run()}
          >
            Add
          </button>
        </div>
      )}
      {can("management", "contributor") && (
        <p className="small muted" style={{ marginTop: -6, marginBottom: "var(--space-4)" }}>
          Whoever you pick is told, and it appears on their dashboard - even if
          they have no other access to this module.
        </p>
      )}

      {add.error && <ErrorNote message={add.error} />}
      {move.error && <ErrorNote message={move.error} />}

      {board.loading ? (
        <Loading />
      ) : board.error ? (
        <ErrorNote message={board.error} onRetry={board.reload} />
      ) : (
        <div className="board">
          {columns.map((column) => {
            const tasks = (board.data?.[column.key] ?? []) as Task[];
            return (
              <section key={column.key} className="board-column">
                <div className="board-head">
                  <span className="field-label">{column.label}</span>
                  <span className="small muted">{tasks.length}</span>
                </div>
                {tasks.length === 0 ? (
                  <p className="small muted board-empty">Nothing here.</p>
                ) : (
                  tasks.map((task) => (
                    <article key={task.id} className="board-card">
                      <div className="strong small">{task.title}</div>
                      <div className="row-tight" style={{ marginTop: 6, flexWrap: "wrap" }}>
                        {task.priority !== "normal" && (
                          <Badge
                            value={task.priority === "urgent" ? "missing" : task.priority === "high" ? "on_loan" : "archived"}
                            kind="status"
                            label={humanise(task.priority)}
                          />
                        )}
                        {task.days_overdue ? (
                          <Badge
                            value="missing"
                            kind="status"
                            label={`${task.days_overdue}d over`}
                          />
                        ) : task.due_on ? (
                          <span className="small muted">{formatDate(task.due_on)}</span>
                        ) : null}
                      </div>
                      {task.assignee_label && (
                        <div className="small muted" style={{ marginTop: 4 }}>
                          {task.assignee_label}
                        </div>
                      )}
                      {column.next && can("management", "contributor") && (
                        <button
                          type="button"
                          className="btn btn-sm"
                          style={{ marginTop: 8 }}
                          disabled={move.running}
                          onClick={() => void move.run(task.id, column.next!)}
                        >
                          {column.next === "done" ? "Mark done" : "Move on"}
                        </button>
                      )}
                    </article>
                  ))
                )}
              </section>
            );
          })}
        </div>
      )}
    </>
  );
}

/* ==========================================================================
 * Calendar
 * ======================================================================= */

/**
 * The shared diary.
 *
 * This is the one screen in the management module that is *not* closed.
 * Everything else here — the funds, the spending — is private by default,
 * because a field director needs no sight of what a conservator is paid. The
 * calendar is the opposite: anybody signed in can read it and add to it,
 * because a diary half the staff cannot write in is a diary that is wrong
 * within a fortnight.
 *
 * Changing an entry is still narrower than adding one: your own, or anybody's
 * if you supervise the module. "Everyone can add a day" and "anyone can move
 * anyone's day" are different propositions.
 *
 * The **activity dropdown** is the part worth explaining. Choosing a previous
 * activity fills in the title, the place, the kind and the project from it, so
 * putting the next season in the diary is one choice rather than five fields —
 * and the entry then links back to everything that season needed.
 */
export function Calendar() {
  const now = new Date();
  const [months, setMonths] = useState(6);
  const [adding, setAdding] = useState(false);

  const events = useQuery<Page<CalendarEvent>>(
    (signal) =>
      api.get(
        "/management/events",
        {
          since: now.toISOString(),
          until: new Date(now.getFullYear(), now.getMonth() + months, now.getDate()).toISOString(),
        },
        signal,
      ),
    [months],
  );

  return (
    <>
      <PageHeader
        title="Calendar"
        subtitle="Everybody's — seasons, deadlines, visits and days off"
        actions={
          <>
            <select
              className="input input-sm filter-select"
              value={months}
              onChange={(event) => setMonths(Number(event.target.value))}
            >
              <option value={3}>Next 3 months</option>
              <option value={6}>Next 6 months</option>
              <option value={12}>Next year</option>
            </select>
            <button className="btn btn-primary" onClick={() => setAdding(true)}>
              Add a day
            </button>
          </>
        }
      />

      {adding && (
        <AddDay
          onClose={() => setAdding(false)}
          onAdded={() => {
            setAdding(false);
            events.reload();
          }}
        />
      )}

      {events.loading ? (
        <Loading />
      ) : events.error ? (
        <ErrorNote message={events.error} onRetry={events.reload} />
      ) : events.data && events.data.items.length === 0 ? (
        <Empty title="Nothing coming up">
          Add a field season, a reporting deadline, a visit — or the day somebody is away. Anyone
          signed in can add to this, and everybody sees it.
        </Empty>
      ) : (
        <section className="card">
          <div className="card-body">
            <ul className="agenda">
              {events.data?.items.map((event) => (
                <li key={event.id}>
                  <div className="agenda-when">
                    <span className="strong">{formatDate(event.starts_at)}</span>
                    {event.ends_at && (
                      <span className="small muted">to {formatDate(event.ends_at)}</span>
                    )}
                  </div>
                  <div className="agenda-what">
                    <span className="strong">{event.title}</span>
                    <span className="small muted">
                      {[event.kind && humanise(event.kind), event.location, event.project_name]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                    {event.activity_id && (
                      <Link className="small" to={`/activities/${event.activity_id}`}>
                        Part of {event.activity_title} — what it takes
                      </Link>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}
    </>
  );
}

function AddDay({ onClose, onAdded }: { onClose: () => void; onAdded: () => void }) {
  const [form, setForm] = useState({
    title: "",
    activity_id: "",
    starts_at: "",
    ends_at: "",
    kind: "",
    location: "",
  });

  // Loaded for anybody signed in, and deliberately thin: it carries a name, a
  // kind, a date and a place, and nothing else. Choosing a season from a list
  // must not hand over its costings.
  const options = useQuery<ActivityOption[]>(
    (signal) => api.get("/activities/options", { limit: 200 }, signal),
    [],
  );

  const chosen = options.data?.find((option) => option.id === form.activity_id);

  const add = useAction(async () => {
    await api.post("/management/events", {
      // Left blank with an activity chosen, the backend fills these in from
      // it. Sending empty strings rather than omitting them would overwrite
      // that with nothing.
      title: form.title || undefined,
      activity_id: form.activity_id || undefined,
      starts_at: new Date(form.starts_at).toISOString(),
      ends_at: form.ends_at ? new Date(form.ends_at).toISOString() : null,
      kind: form.kind || undefined,
      location: form.location || undefined,
    });
    onAdded();
  });

  return (
    <div className="modal-scrim" role="dialog" aria-modal="true">
      <div className="modal">
        <h2 className="modal-title">Add a day</h2>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            void add.run();
          }}
        >
          {add.error && <ErrorNote message={add.error} />}

          <div className="field">
            <label className="field-label" htmlFor="day-activity">
              Part of
            </label>
            <select
              id="day-activity"
              className="input select"
              value={form.activity_id}
              onChange={(event) => setForm({ ...form, activity_id: event.target.value })}
            >
              <option value="">Nothing in particular</option>
              {options.data?.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
            <p className="field-help">
              {chosen
                ? `Anything you leave blank below is taken from "${chosen.title}".`
                : "Pick a previous activity and this day fills itself in from it."}
            </p>
          </div>

          <div className="field">
            <label className="field-label" htmlFor="day-title">
              What is it?
            </label>
            <input
              id="day-title"
              className="input"
              required={!form.activity_id}
              value={form.title}
              onChange={(event) => setForm({ ...form, title: event.target.value })}
              placeholder={chosen ? chosen.title : "Field season, deadline, visit, day off…"}
            />
          </div>

          <div className="row">
            <div className="field col">
              <label className="field-label" htmlFor="day-from">
                From
              </label>
              <input
                id="day-from"
                className="input"
                type="datetime-local"
                required
                value={form.starts_at}
                onChange={(event) => setForm({ ...form, starts_at: event.target.value })}
              />
            </div>
            <div className="field col">
              <label className="field-label" htmlFor="day-to">
                To
              </label>
              <input
                id="day-to"
                className="input"
                type="datetime-local"
                value={form.ends_at}
                onChange={(event) => setForm({ ...form, ends_at: event.target.value })}
              />
            </div>
          </div>

          <div className="field">
            <label className="field-label" htmlFor="day-where">
              Where
            </label>
            <input
              id="day-where"
              className="input"
              value={form.location}
              onChange={(event) => setForm({ ...form, location: event.target.value })}
              placeholder={chosen?.location ?? ""}
            />
          </div>

          <div className="row-tight">
            <button className="btn" type="button" onClick={onClose}>
              Cancel
            </button>
            <button className="btn btn-primary" type="submit" disabled={add.running}>
              {add.running ? "Adding…" : "Add it"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
