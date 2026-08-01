/** Small presentational pieces shared across screens. */

import type { ReactNode } from "react";
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
export function Loading({ rows = 5, label }: { rows?: number; label?: string }) {
  return (
    <div className="col" aria-busy="true" aria-live="polite">
      <span className="sr-only">{label ?? "Loading"}</span>
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="skeleton" style={{ height: 34, opacity: 1 - index * 0.13 }} />
      ))}
    </div>
  );
}

export function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="alert alert-danger">
      <div className="col" style={{ gap: "var(--space-2)" }}>
        <span>{message}</span>
        {onRetry && (
          <button type="button" className="btn btn-sm" onClick={onRetry}>
            Try again
          </button>
        )}
      </div>
    </div>
  );
}

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
      {action}
    </div>
  );
}

/* --------------------------------------------------------------------------
 * Badges with meaning attached
 * ----------------------------------------------------------------------- */
const REVIEW_TONE: Record<string, string> = {
  approved: "badge-success",
  pending: "badge-warning",
  rejected: "badge-danger",
  draft: "",
};

const STATUS_TONE: Record<string, string> = {
  active: "badge-success",
  open: "badge-success",
  accessioned: "badge-success",
  on_display: "badge-info",
  on_loan: "badge-warning",
  in_conservation: "badge-warning",
  planned: "",
  planning: "",
  suspended: "badge-warning",
  completed: "badge-info",
  archived: "",
  deaccessioned: "badge-danger",
  missing: "badge-danger",
  destroyed: "badge-danger",
};

const CONDITION_TONE: Record<string, string> = {
  excellent: "badge-success",
  good: "badge-success",
  fair: "badge-warning",
  poor: "badge-danger",
  fragmentary: "badge-danger",
  unknown: "",
};

export function humanise(value: string) {
  return value.replace(/_/g, " ").replace(/^./, (character) => character.toUpperCase());
}

export function Badge({
  value,
  kind = "plain",
}: {
  value?: string | null;
  kind?: "plain" | "review" | "status" | "condition" | "accent";
}) {
  if (!value) return null;
  const tone =
    kind === "review"
      ? REVIEW_TONE[value]
      : kind === "status"
        ? STATUS_TONE[value]
        : kind === "condition"
          ? CONDITION_TONE[value]
          : kind === "accent"
            ? "badge-accent"
            : "";
  return <span className={`badge ${tone ?? ""}`}>{humanise(value)}</span>;
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
