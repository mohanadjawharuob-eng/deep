/**
 * Search across everything.
 *
 * The backend refuses an unbounded search of the whole database, which is
 * right, so this screen asks for nothing until there is something to ask.
 */

import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "../lib/api";
import { useDebounced, useQuery } from "../lib/hooks";
import {
  Empty,
  ErrorNote,
  Loading,
  PageHeader,
  SearchInput,
  formatRange,
  humanise,
} from "../components/ui";

type Hit = {
  id: string;
  resource_type: string;
  title: string;
  subtitle: string | null;
  description: string | null;
  date_from: number | null;
  date_to: number | null;
};

type Results = { query: string | null; total: number; counts: Record<string, number>; items: Hit[] };

const ROUTE: Record<string, (id: string) => string> = {
  project: (id) => `/projects/${id}`,
  site: (id) => `/sites/${id}`,
  artifact: (id) => `/artifacts/${id}`,
  context: (id) => `/contexts/${id}`,
};

export function Search() {
  const [params, setParams] = useSearchParams();
  const [term, setTerm] = useState(params.get("q") ?? "");
  const [type, setType] = useState(params.get("type") ?? "");
  const debounced = useDebounced(term, 350);

  const results = useQuery<Results>(
    (signal) => {
      setParams(
        type ? { q: debounced, type } : { q: debounced },
        { replace: true },
      );
      return api.get("/search", { q: debounced, types: type || undefined, limit: 60 }, signal);
    },
    [debounced, type],
    { enabled: debounced.trim().length > 1 },
  );

  const counts = results.data?.counts ?? {};

  return (
    <>
      <PageHeader
        title="Search"
        subtitle="Projects, sites, finds and contexts — whatever you may see."
      />

      <div className="toolbar">
        <SearchInput value={term} onChange={setTerm} placeholder="Search everything…" autoFocus />
        <div className="row-tight wrap">
          <button
            type="button"
            className={`btn btn-sm ${type === "" ? "btn-primary" : ""}`}
            onClick={() => setType("")}
          >
            Everything
          </button>
          {Object.entries(counts).map(([key, value]) => (
            <button
              key={key}
              type="button"
              className={`btn btn-sm ${type === key ? "btn-primary" : ""}`}
              onClick={() => setType(type === key ? "" : key)}
            >
              {humanise(key)} <span className="muted">{value}</span>
            </button>
          ))}
        </div>
      </div>

      {debounced.trim().length <= 1 ? (
        <Empty title="Type to search">
          Two characters is enough to start. Press <kbd>/</kbd> anywhere in the platform to come
          back here.
        </Empty>
      ) : results.loading ? (
        <Loading />
      ) : results.error ? (
        <ErrorNote message={results.error} onRetry={results.reload} />
      ) : results.data?.items.length === 0 ? (
        <Empty title={`Nothing matched “${debounced}”`}>
          Try a shorter term, or a number rather than a name.
        </Empty>
      ) : (
        <>
          <p className="small muted">
            {results.data?.total.toLocaleString()} result
            {results.data?.total === 1 ? "" : "s"}
          </p>
          <ul className="results">
            {results.data?.items.map((hit) => {
              const to = ROUTE[hit.resource_type]?.(hit.id);
              const dates = formatRange(hit.date_from, hit.date_to);
              return (
                <li key={`${hit.resource_type}-${hit.id}`} className="result">
                  <div className="result-type">{humanise(hit.resource_type)}</div>
                  <div style={{ minWidth: 0 }}>
                    <div className="strong">
                      {to ? <Link to={to}>{hit.title}</Link> : hit.title}
                    </div>
                    {hit.subtitle && <div className="small muted">{hit.subtitle}</div>}
                    {hit.description && <p className="small clamp-2">{hit.description}</p>}
                    {dates && <div className="small muted">{dates}</div>}
                  </div>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </>
  );
}
