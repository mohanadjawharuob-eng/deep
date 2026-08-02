/**
 * The application frame: sidebar, header, and the outlet everything renders
 * into.
 *
 * The sidebar shows only the modules this user can reach. That is not
 * cosmetic — the platform's whole permission model is per module, and a
 * navigation item leading to a 403 teaches people to distrust the interface.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import type { ModuleName } from "../lib/api";
import { useSession, useTheme } from "../lib/hooks";
import { humanise } from "./ui";

type NavItem = {
  to: string;
  label: string;
  icon: ReactNode;
  module?: ModuleName;
  end?: boolean;
};

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

const SECTIONS: { heading: string | null; items: NavItem[] }[] = [
  {
    heading: null,
    items: [
      { to: "/", label: "Dashboard", end: true, icon: icon("M3 10h5V3H3zm9 7h5V3h-5zM3 17h5v-4H3z") },
      { to: "/search", label: "Search", icon: icon("M9 15A6 6 0 1 0 9 3a6 6 0 0 0 0 12Zm4.5-1.5L17 17") },
    ],
  },
  {
    heading: "Archaeology",
    items: [
      {
        to: "/projects",
        label: "Projects",
        module: "archaeology",
        icon: icon("M3 5.5A1.5 1.5 0 0 1 4.5 4h3l1.5 2h6.5A1.5 1.5 0 0 1 17 7.5v7A1.5 1.5 0 0 1 15.5 16h-11A1.5 1.5 0 0 1 3 14.5z"),
      },
      {
        to: "/sites",
        label: "Sites",
        module: "archaeology",
        icon: icon("M10 17s5.5-4.9 5.5-9a5.5 5.5 0 1 0-11 0c0 4.1 5.5 9 5.5 9Zm0-7.2a1.8 1.8 0 1 0 0-3.6 1.8 1.8 0 0 0 0 3.6Z"),
      },
      {
        to: "/artifacts",
        label: "Finds",
        module: "archaeology",
        icon: icon("M6 3h8l2 5-6 9-6-9zM4 8h12M8.5 3 7 8l3 9M11.5 3 13 8l-3 9"),
      },
      {
        to: "/map",
        label: "Map",
        module: "archaeology",
        icon: icon("M2.5 5.5 7 3.5l6 2 4.5-2v11l-4.5 2-6-2-4.5 2zM7 3.5v11m6-9v11"),
      },
    ],
  },
  {
    heading: "Museum",
    items: [
      {
        to: "/museum",
        label: "Catalogue",
        module: "museum",
        icon: icon("M3 7.5 10 4l7 3.5M4 8v7m4-7v7m4-7v7m4-7v7M2.5 16.5h15"),
      },
      {
        to: "/museum/grid",
        label: "Grid",
        module: "museum",
        icon: icon("M3 3h14v14H3zM3 7.5h14M3 12.5h14M8 3v14m4.5-14v14"),
      },
      {
        to: "/museum/collections",
        label: "Collections",
        module: "museum",
        icon: icon("M4 6h12M4 10h12M4 14h12"),
      },
      {
        to: "/museum/import",
        label: "Import",
        module: "museum",
        icon: icon("M10 12.5V3m0 0L6.5 6.5M10 3l3.5 3.5M3.5 13.5v2A1.5 1.5 0 0 0 5 17h10a1.5 1.5 0 0 0 1.5-1.5v-2"),
      },
    ],
  },
  {
    heading: "Inventory",
    items: [
      {
        to: "/inventory/equipment",
        label: "Equipment",
        module: "inventory",
        icon: icon("M4 7h12v9H4zM7 7V4.5h6V7M2.5 11h15"),
      },
      {
        to: "/inventory/stock",
        label: "Stock",
        module: "inventory",
        icon: icon("M3 6.5 10 3l7 3.5v7L10 17l-7-3.5zM3 6.5 10 10m0 0 7-3.5M10 10v7"),
      },
      {
        to: "/inventory/kit-templates",
        label: "Kits",
        module: "inventory",
        icon: icon("M3.5 6.5h13v10h-13zM7 6.5V4h6v2.5M3.5 10.5h13"),
      },
    ],
  },
  {
    heading: "Store",
    items: [
      {
        to: "/storage",
        label: "Locations",
        icon: icon("M3 7.5 10 4l7 3.5v9L10 20l-7-3.5zM3 7.5 10 11l7-3.5M10 11v9"),
      },
      {
        to: "/floorplans",
        label: "Floor plans",
        icon: icon("M3 3h14v14H3zM3 8h7m0-5v14m0-5h7"),
      },
    ],
  },
];

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

  const visible = SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter((item) => !item.module || levelIn(item.module)),
  })).filter((section) => section.items.length > 0);

  const initials = (user?.full_name ?? user?.username ?? "?")
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");

  return (
    <div className={`shell ${navOpen ? "nav-open" : ""}`}>
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="brand-mark">
            <BrandMark />
          </span>
          <span className="brand-text">
            <strong>Stratum</strong>
          </span>
        </div>

        <nav className="sidebar-nav">
          {visible.map((section) => (
            <div key={section.heading ?? "main"} className="nav-section">
              {section.heading && <div className="nav-heading">{section.heading}</div>}
              {section.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
                >
                  {item.icon}
                  <span>{item.label}</span>
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <div className="sidebar-foot">
          <span className="avatar">{initials}</span>
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
              platform whose records are found by accession number, the box a
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
              placeholder="Search records, sites, accession numbers…"
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
              <span className="avatar">{initials}</span>
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

        <main className="content">
          <Outlet />
        </main>
      </div>

      {navOpen && <div className="nav-scrim" onClick={() => setNavOpen(false)} />}
    </div>
  );
}
