/** Small presentational pieces shared across screens. */

import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

/* --------------------------------------------------------------------------
 * Page furniture
 * ----------------------------------------------------------------------- */
export function PageHeader({
  title,
  subtitle,
  actions,
  breadcrumb,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  breadcrumb?: { label: string; to?: string }[];
}) {
  return (
    <header className="page-header">
      {breadcrumb && breadcrumb.length > 0 && (
        <nav className="breadcrumb" aria-label="Breadcrumb">
          {breadcrumb.map((crumb, index) => (
            <span key={`${crumb.label}-${index}`}>
              {index > 0 && <span className="breadcrumb-sep">/</span>}
              {crumb.to ? <Link to={crumb.to}>{crumb.label}</Link> : <span>{crumb.label}</span>}
            </span>
          ))}
        </nav>
      )}
      <div className="page-header-main">
        <div className="page-header-text">
          <h1>{title}</h1>
          {subtitle && <p className="page-subtitle">{subtitle}</p>}
        </div>
        {actions && <div className="row-tight wrap">{actions}</div>}
      </div>
    </header>
  );
}

/* --------------------------------------------------------------------------
 * States
 * ----------------------------------------------------------------------- */
/**
 * A skeleton shaped like the rows it is standing in for.
 *
 * Deliberately not a spinner. A spinner says "something is happening"; a
 * skeleton says "a table of this shape is arriving", which stops the page
 * jumping when it does.
 */
export function Loading({ rows = 5, label }: { rows?: number; label?: string }) {
  return (
    <div className="card" aria-busy="true" aria-live="polite">
      <span className="sr-only">{label ?? "Loading"}</span>
      <div style={{ padding: "12px 14px" }}>
        {Array.from({ length: rows }, (_, index) => (
          <div
            key={index}
            style={{
              display: "flex",
              gap: 14,
              alignItems: "center",
              padding: "7px 0",
              borderBottom: "1px solid var(--border)",
            }}
          >
            <div
              className="skeleton"
              style={{ width: 96, height: 11, animationDelay: `${index * 0.06}s` }}
            />
            <div
              className="skeleton"
              style={{ flex: 1, height: 11, animationDelay: `${index * 0.06 + 0.1}s` }}
            />
            <div
              className="skeleton"
              style={{ width: 78, height: 11, animationDelay: `${index * 0.06 + 0.2}s` }}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

const ALERT_ICON = (
  <svg
    viewBox="0 0 24 24"
    width="17"
    height="17"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
    strokeLinecap="round"
    aria-hidden="true"
    style={{ marginTop: 1, flexShrink: 0 }}
  >
    <circle cx="12" cy="12" r="9" />
    <path d="M12 8v5M12 16h.01" />
  </svg>
);

/**
 * A failure, said plainly.
 *
 * Two things the design insists on and this implements: say whether anything
 * was changed, and show the request that failed. "Something went wrong" tells
 * a curator nothing they can act on or report.
 */
export function ErrorNote({
  message,
  onRetry,
  detail,
}: {
  message: string;
  onRetry?: () => void;
  /** The request that failed, for a bug report. */
  detail?: string;
}) {
  return (
    <div className="alert alert-danger" role="alert">
      <span style={{ color: "var(--danger)" }}>{ALERT_ICON}</span>
      <div style={{ flex: 1 }}>
        <div className="strong" style={{ color: "var(--danger)" }}>
          {message}
        </div>
        <div className="small" style={{ marginTop: 2 }}>
          Nothing was changed.
          {detail && <span className="mono"> {detail}</span>}
        </div>
        {onRetry && (
          <button
            type="button"
            className="btn btn-sm btn-danger"
            style={{ marginTop: 9 }}
            onClick={onRetry}
          >
            Try again
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * Nothing here — and what to do about it.
 *
 * A new institution's platform is entirely empty states for its first week,
 * so each one names the next action rather than apologising.
 */
export function Empty({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-title">{title}</div>
      {children && <p>{children}</p>}
      {action && (
        <div className="row-tight wrap" style={{ justifyContent: "center" }}>
          {action}
        </div>
      )}
    </div>
  );
}

/* --------------------------------------------------------------------------
 * Badges with meaning attached
 * ----------------------------------------------------------------------- */
/**
 * A badge's tone and its *mark*.
 *
 * The mark is not decoration. Stratum's rule is that meaning is never carried
 * by colour alone: a red pill and a green pill are the same pill to a
 * colour-blind reader, to a monochrome printer, and to anyone glancing at a
 * screen in the sun outside a trench. The glyph and — for anything provisional
 * — the dashed border carry the same information the hue does.
 */
type Tone = { className: string; mark?: string };

const REVIEW_TONE: Record<string, Tone> = {
  approved: { className: "badge-success", mark: "✓" },
  pending: { className: "badge-warning", mark: "◔" },
  rejected: { className: "badge-danger", mark: "!" },
  draft: { className: "", mark: "·" },
};

const STATUS_TONE: Record<string, Tone> = {
  active: { className: "badge-success", mark: "✓" },
  open: { className: "badge-success", mark: "✓" },
  accessioned: { className: "badge-success", mark: "✓" },
  on_display: { className: "badge-info" },
  on_loan: { className: "badge-warning", mark: "◔" },
  in_conservation: { className: "badge-warning", mark: "◔" },
  temporary: { className: "badge-warning", mark: "◔" },
  planned: { className: "" },
  planning: { className: "" },
  suspended: { className: "badge-warning", mark: "◔" },
  completed: { className: "badge-info" },
  archived: { className: "" },
  deaccessioned: { className: "badge-danger", mark: "!" },
  missing: { className: "badge-danger", mark: "!" },
  destroyed: { className: "badge-danger", mark: "!" },

  // Equipment. "Available" is the only one that means you can take it out
  // tomorrow, so it is the only green one — an amber checked-out badge would
  // read as a warning about an item that is doing exactly what it should.
  available: { className: "badge-success", mark: "✓" },
  checked_out: { className: "badge-info" },
  in_repair: { className: "badge-warning", mark: "◔" },
  out_for_calibration: { className: "badge-warning", mark: "◔" },
  retired: { className: "" },
};

const CONDITION_TONE: Record<string, Tone> = {
  excellent: { className: "badge-success", mark: "✓" },
  good: { className: "badge-success", mark: "✓" },
  fair: { className: "badge-info" },
  poor: { className: "badge-warning", mark: "◔" },
  fragmentary: { className: "badge-danger", mark: "!" },
  unknown: { className: "" },
};

export function humanise(value: string) {
  return value.replace(/_/g, " ").replace(/^./, (character) => character.toUpperCase());
}

export function Badge({
  value,
  kind = "plain",
  label,
}: {
  value?: string | null;
  kind?: "plain" | "review" | "status" | "condition" | "accent";
  /** Override the displayed text; the tone still comes from `value`. */
  label?: string;
}) {
  if (!value) return null;

  const tone: Tone =
    kind === "review"
      ? (REVIEW_TONE[value] ?? { className: "" })
      : kind === "status"
        ? (STATUS_TONE[value] ?? { className: "" })
        : kind === "condition"
          ? (CONDITION_TONE[value] ?? { className: "" })
          : kind === "accent"
            ? { className: "badge-accent" }
            : { className: "" };

  return (
    <span className={`badge ${tone.className}`}>
      {tone.mark && (
        <span className="badge-mark" aria-hidden="true">
          {tone.mark}
        </span>
      )}
      {label ?? humanise(value)}
    </span>
  );
}

/**
 * A number that does not match its collection's pattern.
 *
 * Dashed, like everything provisional in this platform. It is a note, not an
 * error: the institution's own number is the object's identity, and a
 * platform that hid or refused it would be a platform they stayed out of.
 */
export function LegacyMark() {
  return (
    <span
      className="badge badge-warning"
      title="Does not match this collection's numbering pattern"
    >
      legacy
    </span>
  );
}

/* --------------------------------------------------------------------------
 * Values
 * ----------------------------------------------------------------------- */

/** A signed year, where negative means BCE — the platform's convention. */
export function formatYear(year?: number | null) {
  if (year === null || year === undefined) return null;
  return year < 0 ? `${Math.abs(year)} BCE` : `${year} CE`;
}

export function formatRange(from?: number | null, to?: number | null) {
  const start = formatYear(from);
  const end = formatYear(to);
  if (start && end) return start === end ? start : `${formatYear(from)} – ${end}`;
  return start ?? end ?? null;
}

export function formatDate(value?: string | null) {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function formatDateTime(value?: string | null) {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** How long ago, for a feed where the exact instant rarely matters. */
export function timeAgo(value?: string | null) {
  if (!value) return "";
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.round((Date.now() - then) / 1000);

  const steps: [number, Intl.RelativeTimeFormatUnit][] = [
    [60, "second"],
    [60, "minute"],
    [24, "hour"],
    [7, "day"],
    [4.35, "week"],
    [12, "month"],
  ];

  let amount = seconds;
  let unit: Intl.RelativeTimeFormatUnit = "second";
  for (const [size, next] of steps) {
    if (Math.abs(amount) < size) break;
    amount = Math.round(amount / size);
    unit = next;
  }
  return new Intl.RelativeTimeFormat(undefined, { numeric: "auto" }).format(-amount, unit);
}

/** A labelled value on a detail card; renders nothing when there is nothing. */
export function Detail({
  label,
  value,
  span = 1,
}: {
  label: string;
  value: ReactNode;
  span?: number;
}) {
  const empty =
    value === null ||
    value === undefined ||
    value === "" ||
    (Array.isArray(value) && value.length === 0);
  if (empty) return null;
  return (
    <div className="detail" style={{ gridColumn: `span ${span}` }}>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

export function DetailGrid({ children }: { children: ReactNode }) {
  return <dl className="detail-grid">{children}</dl>;
}

/* --------------------------------------------------------------------------
 * Pagination
 * ----------------------------------------------------------------------- */
export function Pager({
  total,
  limit,
  offset,
  onChange,
}: {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
}) {
  if (total <= limit) return null;
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.ceil(total / limit);

  return (
    <div className="pager">
      <span className="small muted">
        {offset + 1}–{Math.min(offset + limit, total)} of {total.toLocaleString()}
      </span>
      <div className="row-tight">
        <button
          type="button"
          className="btn btn-sm"
          onClick={() => onChange(Math.max(0, offset - limit))}
          disabled={offset === 0}
        >
          Previous
        </button>
        <span className="small muted mono">
          {page} / {pages}
        </span>
        <button
          type="button"
          className="btn btn-sm"
          onClick={() => onChange(offset + limit)}
          disabled={offset + limit >= total}
        >
          Next
        </button>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------------------
 * Search box
 * ----------------------------------------------------------------------- */
export function SearchInput({
  value,
  onChange,
  placeholder = "Search…",
  autoFocus,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
}) {
  return (
    <div className="search">
      <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
        <path
          d="M7 12A5 5 0 1 0 7 2a5 5 0 0 0 0 10Zm4-1 3.5 3.5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
        />
      </svg>
      <input
        className="input"
        type="search"
        value={value}
        placeholder={placeholder}
        autoFocus={autoFocus}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}

/* --------------------------------------------------------------------------
 * Confirming something irreversible
 * ----------------------------------------------------------------------- */

/**
 * A confirmation that names the thing and lists what goes with it.
 *
 * "Are you sure?" is not a question anybody answers carefully. Naming the
 * object — and saying that its conservation history and four photographs are
 * deleted with it — is what makes the second thought possible. The confirming
 * button repeats the identifier, so a mis-click on a stale dialogue is a
 * mis-click on a visibly wrong name.
 */
export function ConfirmDelete({
  name,
  title = "Delete this record?",
  consequences,
  busy,
  onCancel,
  onConfirm,
}: {
  /** The identifier, shown in monospace and repeated on the button. */
  name: string;
  title?: string;
  consequences?: ReactNode;
  busy?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  // Escape cancels. A modal that traps you is a modal people learn to dread.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div
      className="modal-scrim"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
    >
      <div className="modal">
        <div className="modal-title">{title}</div>
        <p className="small" style={{ margin: "6px 0 14px", color: "var(--text-2)" }}>
          You are about to delete <span className="mono">{name}</span>.{" "}
          {consequences ?? "This cannot be undone."}
        </p>
        <div className="row-tight" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn" onClick={onCancel} disabled={busy}>
            Keep it
          </button>
          <button
            type="button"
            className="btn btn-danger-solid"
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? "Deleting…" : `Delete ${name}`}
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * The delete button, and everything that has to happen around one.
 *
 * Deleting is the one action nobody can undo by clicking again, so the same
 * three things are true everywhere and are done here once rather than in every
 * screen that offers it:
 *
 * - **It asks first**, naming the record, so a mis-click on a list costs a
 *   glance rather than a season.
 * - **It says what else goes.** Deleting a site takes its contexts and its
 *   finds with it, and somebody who did not know that is somebody about to
 *   find out the hard way.
 * - **It says a copy is kept.** The server writes the record and everything
 *   under it to a file before the row goes. That is the difference between a
 *   frightening button and a safe one, and it is worth saying at the moment
 *   the fear is felt rather than in documentation nobody opens.
 *
 * Nothing is rendered at all when `can` is false — an offer to delete that
 * ends in "you may not" wastes the one click somebody was sure about.
 */
export function DeleteRecord({
  name,
  label = "Delete",
  title,
  takesWithIt,
  can = true,
  onDelete,
  onDeleted,
}: {
  /** What the record is called. Shown in the dialog and on the button. */
  name: string;
  label?: string;
  title?: string;
  /** What else goes with it: "its contexts and its finds". */
  takesWithIt?: string;
  can?: boolean;
  onDelete: () => Promise<unknown>;
  onDeleted?: () => void;
}) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);

  if (!can) return null;

  async function confirm() {
    setBusy(true);
    setFailed(null);
    try {
      await onDelete();
      setAsking(false);
      onDeleted?.();
    } catch (cause) {
      setFailed(cause instanceof Error ? cause.message : "It could not be deleted.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button type="button" className="btn btn-danger" onClick={() => setAsking(true)}>
        {label}
      </button>

      {asking && (
        <ConfirmDelete
          name={name}
          title={title ?? "Delete this record?"}
          busy={busy}
          onCancel={() => setAsking(false)}
          onConfirm={() => void confirm()}
          consequences={
            <>
              {takesWithIt ? `This also deletes ${takesWithIt}. ` : ""}
              A copy of it — and everything under it — is written to a file on
              this computer first, so it can be recovered from there.
              {failed && (
                <span className="strong" style={{ display: "block", marginTop: 8 }}>
                  {failed}
                </span>
              )}
            </>
          }
        />
      )}
    </>
  );
}
