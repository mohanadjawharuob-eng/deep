/**
 * The application frame: sidebar, header, and the outlet everything renders
 * into.
 *
 * The sidebar shows only the modules this user can reach. That is not
 * cosmetic — the platform's whole permission model is per module, and a
 * navigation item leading to a 403 teaches people to distrust the interface.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { api, type ModuleName } from "../lib/api";
import { useBranding, useQuery, useSession, useTheme } from "../lib/hooks";
import { Avatar, humanise } from "./ui";

/** The mark: three strata cut by two section lines. */
export const BrandMark = ({ size = 20 }: { size?: number }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M3 17.5h18M3 12.5h18M3 7.5h18" />
    <path d="M8 3v18M16 3v18" opacity=".35" />
  </svg>
);

/**
 * Whose installation this is, at the top of the sidebar.
 *
 * An institution that has put its collection into this platform should see its
 * own mark on the page it works in all day. Where nothing has been uploaded,
 * the platform's own mark is drawn — a blank space would look like a page that
 * failed to load.
 */
export function Brand({ compact = false }: { compact?: boolean }) {
  const { branding } = useBranding();

  return (
    <div className="sidebar-brand">
      <span className="brand-mark">
        {branding.logo_url ? (
          <img className="brand-logo" src={branding.logo_url} alt="" />
        ) : (
          <BrandMark />
        )}
      </span>
      {!compact && (
        <span className="brand-text">
          <strong className="truncate">{branding.display_name}</strong>
          {branding.tagline && <span className="small truncate">{branding.tagline}</span>}
        </span>
      )}
    </div>
  );
}

/**
 * Whether a link that carries a query is the one we are actually on.
 *
 * React Router matches on the path alone, so "Import" under Archaeology and
 * "Import" under Museum — the same screen with a different preset — both light
 * up at once, and the sidebar claims you are in two places. Links with no query
 * are unaffected.
 */
function queryMatches(to: string, search: string): boolean {
  const [, query] = to.split("?");
  if (!query) return true;
  const wanted = new URLSearchParams(query);
  const actual = new URLSearchParams(search);
  return [...wanted].every(([key, value]) => actual.get(key) === value);
}

const icon = (path: string) => (
  <svg viewBox="0 0 20 20" width="17" height="17" aria-hidden="true">
    <path
      d={path}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

/**
 * The five places, and what lives in each of them.
 *
 * The sidebar used to list twenty-two destinations across eight headings, and
 * a screen could be reached two different ways with two different names —
 * "Import" appeared twice, "Activities" and "Activity hub" were different
 * words for one thing. Two competing systems in one sidebar is worse than
 * either of them alone, because neither one can be learned.
 *
 * So: five destinations, and everything else is reached from the destination
 * it belongs to, through the bar under the header. Nothing is removed and no
 * URL changes — screens stop being *listed*, not stop existing. Several that
 * were never in the sidebar at all (out on loan, kits in use, spending) are
 * reachable from the navigation for the first time.
 *
 * `owns` decides which bar you see. It is a list of path prefixes, and one of
 * them may carry a query, because the importer is one screen that belongs to
 * whichever workspace the record type says: `/import?type=museum_object` is
 * the museum's, `/import` is the excavation's.
 */

type Place = {
  to: string;
  label: string;
  module?: ModuleName;
  end?: boolean;
  /**
   * Query keys this screen understands as "show me only this one's".
   *
   * Without them the bar quietly loses your place: open a project, click
   * Sites, and you are looking at every site in the institution under your
   * project's heading. Every list screen already honours these when they are
   * in the URL - the bar simply was not passing them on.
   */
  keeps?: readonly string[];
};

/** Every key that narrows a screen, and the record kind behind it. */
const SCOPES = [
  { key: "project_id", endpoint: "/projects", fields: ["code", "name"] },
  { key: "site_id", endpoint: "/sites", fields: ["code", "name"] },
  { key: "collection_id", endpoint: "/museum/collections", fields: ["code", "name"] },
] as const;

type Destination = Place & {
  icon: ReactNode;
  /** Path prefixes — and at most one query — that show this destination's bar. */
  owns: string[];
  places: Place[];
};

const DESTINATIONS: Destination[] = [
  {
    to: "/",
    label: "Today",
    end: true,
    // A sun over the horizon: what is happening now, rather than what is kept.
    icon: icon("M10 3v2m0 10.5a4 4 0 1 1 0-8 4 4 0 0 1 0 8M3.5 15.5h13M4.8 6.3l1.4 1.4m9-1.4-1.4 1.4"),
    owns: ["/", "/my-work", "/data-requests", "/activities", "/management"],
    places: [
      { to: "/", label: "Overview", end: true },
      { to: "/my-work", label: "My work" },
      { to: "/data-requests", label: "Requests" },
      // Not `end`: the hub, the full list and a single activity are all
      // "Activities", and a tab that goes dark one click in reads as having
      // left the place you are still standing in.
      { to: "/activities", label: "Activities" },
      { to: "/management/calendar", label: "Calendar" },
      { to: "/management/tasks", label: "Tasks", module: "management" },
      { to: "/management/budgets", label: "Funds", module: "management" },
      { to: "/management/expenses", label: "Spending", module: "management" },
    ],
  },
  {
    to: "/projects",
    label: "Excavations",
    module: "archaeology",
    icon: icon("M10 17s5.5-4.9 5.5-9a5.5 5.5 0 1 0-11 0c0 4.1 5.5 9 5.5 9Zm0-7.2a1.8 1.8 0 1 0 0-3.6 1.8 1.8 0 0 0 0 3.6Z"),
    owns: ["/projects", "/sites", "/contexts", "/artifacts", "/map", "/import", "/tray"],
    places: [
      { to: "/projects", label: "Projects" },
      { to: "/sites", label: "Sites", keeps: ["project_id"] },
      { to: "/artifacts", label: "Finds", keeps: ["project_id", "site_id"] },
      { to: "/map", label: "Map", keeps: ["project_id"] },
      { to: "/tray?type=artifact", label: "Register a tray" },
      { to: "/import?type=excavation_context", label: "Import" },
    ],
  },
  {
    to: "/museum/collections",
    // "Museum", not "Collections". The sidebar names places the way the people
    // who work there name them, and "Collections" is also the name of a screen
    // *inside* this one - two things called the same thing at two levels.
    label: "Museum",
    module: "museum",
    icon: icon("M3 7.5 10 4l7 3.5M4 8v7m4-7v7m4-7v7m4-7v7M2.5 16.5h15"),
    owns: ["/museum", "/import?type=museum_object", "/tray?type=museum_object"],
    places: [
      { to: "/museum/collections", label: "Collections" },
      { to: "/museum", label: "Catalogue", end: true, keeps: ["collection_id"] },
      { to: "/museum/grid", label: "Grid", keeps: ["collection_id"] },
      { to: "/tray?type=museum_object", label: "Register a tray" },
      { to: "/import?type=museum_object", label: "Import" },
    ],
  },
  {
    to: "/library",
    label: "Library",
    // Under archaeology rather than a module of its own: a bibliography is not
    // secret, and a seventh module would mean one more grant on every account
    // before anybody could look a reference up.
    module: "archaeology",
    icon: icon("M10 5.5C8.5 4.5 6.5 4 4 4v11c2.5 0 4.5.5 6 1.5 1.5-1 3.5-1.5 6-1.5V4c-2.5 0-4.5.5-6 1.5zM10 5.5v11"),
    owns: ["/library"],
    places: [],
  },
  {
    to: "/media",
    label: "Media",
    // A stack of pictures.
    icon: icon("M6 3.5h11v11H6zM3 6.5v10h10M9 11l2.5-2.5L14 11l1.5-1.5"),
    owns: ["/media", "/photographs"],
    places: [
      { to: "/media", label: "Folders" },
      { to: "/photographs", label: "Everything" },
    ],
  },
  {
    to: "/social",
    // "Social media", not "Outreach". I folded this into Today under a name
    // I preferred, and it became unfindable - somebody looking for the thing
    // they call social media will not recognise a word I chose instead. The
    // critique argued for cutting this module; that was a recommendation, and
    // it was declined.
    label: "Social media",
    module: "social_media",
    // A speech bubble.
    icon: icon("M4 4.5h12v9H9l-4 3v-3H4zM7 7.5h6M7 10.5h4"),
    owns: ["/social"],
    places: [
      { to: "/social", label: "Posts", end: true },
      { to: "/social/accounts", label: "Channels" },
    ],
  },
  {
    to: "/storage",
    label: "Store",
    // Everything that answers "where is the physical thing" — the shelf, the
    // room, the trowel and the box of finds bags alike.
    icon: icon("M3 7.5 10 4l7 3.5v6L10 17l-7-3.5zM3 7.5 10 11l7-3.5M10 11v6"),
    owns: ["/storage", "/floorplans", "/inventory"],
    places: [
      { to: "/storage", label: "Locations" },
      { to: "/floorplans", label: "Floor plans" },
      { to: "/inventory/equipment", label: "Equipment", module: "inventory" },
      { to: "/inventory/out", label: "Out on loan", module: "inventory" },
      { to: "/inventory/stock", label: "Stock", module: "inventory" },
      { to: "/inventory/kit-templates", label: "Kits", module: "inventory" },
    ],
  },
];

/** Screens that belong to the account rather than to any destination. */
const ACCOUNT: (Place & { adminOnly?: boolean })[] = [
  { to: "/profile", label: "My profile" },
  // The one screen that can hand somebody the keys to every other one.
  { to: "/admin/users", label: "People", adminOnly: true },
  // The name and mark at the top of every page: an institutional decision,
  // not a preference, so it is the administrator's and nobody else's.
  { to: "/admin/appearance", label: "Appearance", adminOnly: true },
  // What the institution records, as opposed to what the software ships
  // with: the same kind of decision as the period list, held by the same
  // people, because everybody fills in the same form.
  { to: "/admin/fields", label: "Our own fields", adminOnly: true },
];

/**
 * Which of the five you are standing in.
 *
 * The longest matching prefix wins, so `/museum/grid` resolves to Collections
 * and not to something shorter that happens to overlap. A prefix carrying a
 * query beats one that does not, which is the whole reason `/import` can be
 * two workspaces' screen without either of them stealing it.
 */
function destinationFor(pathname: string, search: string): Destination | undefined {
  let best: Destination | undefined;
  let bestScore = -1;

  for (const destination of DESTINATIONS) {
    for (const spec of destination.owns) {
      const [path = "/", query] = spec.split("?");
      const hit = path === "/" ? pathname === "/" : pathname === path || pathname.startsWith(`${path}/`);
      if (!hit || !queryMatches(spec, search)) continue;
      const score = path.length * 2 + (query ? 1 : 0);
      if (score > bestScore) {
        bestScore = score;
        best = destination;
      }
    }
  }
  return best;
}

/**
 * What the screen is narrowed to, named, with a way out.
 *
 * A filter that persists and is not visible is a trap: you look at eleven
 * finds, conclude the site has eleven, and are wrong. So the scope is stated
 * in words at the top of the bar, with the record's own code, and one click
 * clears it.
 */
function ScopeChip({
  scope,
  onClear,
}: {
  scope: { key: string; id: string; endpoint: string; fields: readonly string[] };
  onClear: () => void;
}) {
  const record = useQuery<Record<string, unknown>>(
    (signal) => api.get(`${scope.endpoint}/${scope.id}`, undefined, signal),
    [scope.endpoint, scope.id],
  );

  const label = scope.fields
    .map((field) => record.data?.[field])
    .filter(Boolean)
    .join(" - ");

  return (
    <span className="scope-chip">
      <span className="truncate">Only {label || "this one"}</span>
      <button type="button" onClick={onClear} title="Show everything again" aria-label="Clear">
        &times;
      </button>
    </span>
  );
}

export function Shell() {
  const { user, signOut, levelIn, access } = useSession();
  const { theme, setTheme } = useTheme();
  const navigate = useNavigate();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [query, setQuery] = useState("");
  const menuRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setNavOpen(false);
    setMenuOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!menuOpen) return;
    const close = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [menuOpen]);

  // "/" focuses search from anywhere, the way every tool people already use
  // behaves. Ignored while typing, so it does not hijack a form.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing =
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable);
      if (event.key === "/" && !typing) {
        event.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate]);

  const mayReach = (place: { module?: ModuleName }) => !place.module || Boolean(levelIn(place.module));

  const destinations = DESTINATIONS.filter(mayReach);

  // Which of the five the current screen belongs to, and the bar for it. A
  // destination the user cannot reach shows no bar — that is the "no module"
  // case, and its screens refuse them anyway.
  const here = destinationFor(location.pathname, location.search);
  const places =
    here && mayReach(here) ? here.places.filter(mayReach) : [];

  // What the current URL narrows things to, if anything.
  const current = new URLSearchParams(location.search);
  const scope = SCOPES.map((item) => ({ ...item, id: current.get(item.key) ?? "" })).find(
    (item) => item.id,
  );

  /** A bar link, carrying the scope to the screens that understand it. */
  const linkFor = (place: Place) => {
    if (!scope || !place.keeps?.includes(scope.key)) return place.to;
    const [path, query] = place.to.split("?");
    const params = new URLSearchParams(query);
    params.set(scope.key, scope.id);
    return `${path}?${params.toString()}`;
  };

  const clearScope = () => {
    const next = new URLSearchParams(location.search);
    for (const item of SCOPES) next.delete(item.key);
    const query = next.toString();
    navigate(`${location.pathname}${query ? `?${query}` : ""}`);
  };

  const who = user?.full_name ?? user?.username ?? null;

  return (
    <div className={`shell ${navOpen ? "nav-open" : ""}`}>
      <aside className="sidebar">
        <Brand />

        {/* Five links. The highlight follows the destination you are standing
            in, not the link you happened to click: opening a site from search
            lights up Excavations, because that is where you are. */}
        <nav className="sidebar-nav">
          {destinations.map((destination) => (
            <NavLink
              key={destination.to}
              to={destination.to}
              className={`nav-item ${destination === here ? "active" : ""}`}
            >
              {destination.icon}
              <span>{destination.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-foot">
          <Avatar userId={user?.id} name={who} hasPhoto={user?.has_avatar ?? true} />
          <span style={{ flex: 1, minWidth: 0 }}>
            <span className="user-name truncate" style={{ display: "block" }}>
              {user?.full_name}
            </span>
            <span className="user-role">
              {access?.is_platform_admin ? "Platform administrator" : (user?.position ?? user?.role)}
            </span>
          </span>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            title="Sign out"
            aria-label="Sign out"
            onClick={() => void signOut()}
          >
            <svg
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
              <path d="m16 17 5-5-5-5M21 12H9" />
            </svg>
          </button>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <button
            type="button"
            className="btn btn-ghost nav-toggle"
            onClick={() => setNavOpen((open) => !open)}
            aria-label="Toggle navigation"
          >
            {icon("M3 6h14M3 10h14M3 14h14")}
          </button>

          {/* Search lives in the header rather than behind an icon: on a
              platform whose records are found by inventory number, the box a
              number is typed into should always be visible. */}
          <form
            className="search"
            role="search"
            onSubmit={(event) => {
              event.preventDefault();
              navigate(`/search?q=${encodeURIComponent(query)}`);
            }}
          >
            <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
              <circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" strokeWidth="1.5" />
              <path d="m20 20-3.6-3.6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <input
              ref={searchRef}
              className="input"
              type="search"
              value={query}
              placeholder="Search records, sites, inventory numbers…"
              aria-label="Search"
              onChange={(event) => setQuery(event.target.value)}
            />
          </form>

          <div className="spacer" />

          <button
            type="button"
            className="btn btn-sm"
            onClick={() => setTheme(theme === "dark" ? "light" : theme === "light" ? "system" : "dark")}
            title={`Theme: ${theme}. Click to change.`}
          >
            {theme === "dark"
              ? icon("M15.5 11.5A6 6 0 0 1 8.5 4.5a6 6 0 1 0 7 7Z")
              : theme === "light"
                ? icon("M10 13.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7ZM10 2v1.5M10 16.5V18M18 10h-1.5M3.5 10H2m12.2-4.2-1 1m-6.4 6.4-1 1m8.4 0-1-1M5.8 5.8l1 1")
                : icon("M10 3v14M10 3a7 7 0 0 0 0 14")}
            <span className="small">{theme === "system" ? "Auto" : humanise(theme)}</span>
          </button>

          <div className="user-menu" ref={menuRef}>
            <button
              type="button"
              className="avatar-button"
              onClick={() => setMenuOpen((open) => !open)}
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              aria-label="Account and module access"
            >
              <Avatar userId={user?.id} name={who} hasPhoto={user?.has_avatar ?? true} />
            </button>

            {menuOpen && (
              <div className="menu" role="menu">
                <div className="menu-header">
                  <div className="strong">{user?.full_name}</div>
                  <div className="small muted">{user?.email}</div>
                </div>
                <div className="menu-section">
                  <div className="small muted menu-label">Module access</div>
                  {access?.is_platform_admin ? (
                    <div className="small">Every module (administrator)</div>
                  ) : Object.keys(access?.access ?? {}).length === 0 ? (
                    <div className="small muted">No modules granted</div>
                  ) : (
                    Object.entries(access?.access ?? {}).map(([module, level]) => (
                      <div key={module} className="menu-access small">
                        <span>{module.replace(/_/g, " ")}</span>
                        <span className="badge">{level}</span>
                      </div>
                    ))
                  )}
                </div>
                {/* Your profile, and — for the administrator — the two
                    screens that govern the whole installation. They are about
                    the account rather than about the work, which is why they
                    are here and no longer taking two rows in the sidebar. */}
                <div className="menu-links">
                  {ACCOUNT.filter(
                    (place) => !place.adminOnly || user?.role === "admin",
                  ).map((place) => (
                    <Link key={place.to} className="menu-item" role="menuitem" to={place.to}>
                      {place.label}
                    </Link>
                  ))}
                </div>
                <button
                  type="button"
                  className="menu-item"
                  role="menuitem"
                  onClick={() => void signOut()}
                >
                  Sign out
                </button>
              </div>
            )}
          </div>
        </header>

        {/* The second level. Every screen that left the sidebar is here,
            under the destination it belongs to, so the sidebar answers "where
            am I" and this answers "what else is here". */}
        {places.length > 1 && (
          <nav className="sectionbar" aria-label={`${here?.label} screens`}>
            {scope && <ScopeChip scope={scope} onClear={clearScope} />}
            {places.map((place) => (
              <NavLink
                key={place.to}
                to={linkFor(place)}
                end={place.end}
                // Matched on the path alone. The two importers are one screen
                // with a different preset, and which workspace it belongs to
                // has already been decided by `destinationFor` — so only one
                // of them is on the page at all, and a bare `/import` with no
                // preset still highlights the tab that leads to it.
                className={({ isActive }) => `sectionbar-item ${isActive ? "active" : ""}`}
              >
                {place.label}
              </NavLink>
            ))}
          </nav>
        )}

        <main className="content">
          <Outlet />
        </main>
      </div>

      {navOpen && <div className="nav-scrim" onClick={() => setNavOpen(false)} />}
    </div>
  );
}
