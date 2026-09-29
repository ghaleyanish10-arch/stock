/* Application shell: sidebar navigation, header, theme toggle, account menu.
 *
 * The nav is intentionally explicit rather than generated from the route table,
 * so grouping and ordering are a design decision instead of an accident.
 */

import { NavLink, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { archive, market } from "../api";
import { useAuth } from "../auth";
import { useTheme, type ThemePreference } from "../theme";
import { fmtDateTime } from "../format";
import { CommandPalette } from "./CommandPalette";
import { HighlightsTicker, IndexBar } from "./MarketBar";

const NAV = [
  {
    group: "Market",
    items: [
      { to: "/", label: "Overview", end: true },
      { to: "/treemap", label: "Heatmap" },
      { to: "/movers", label: "Movers" },
      { to: "/stocks", label: "Stocks" },
    ],
  },
  {
    group: "Analysis",
    items: [
      { to: "/archive", label: "Archive" },
      { to: "/screener", label: "Screener" },
      { to: "/analytics", label: "Technical" },
    ],
  },
  {
    group: "Personal Tools",
    items: [
      { to: "/portfolio", label: "Portfolio" },
      { to: "/watchlist", label: "Watchlists" },
      { to: "/alerts", label: "Alerts" },
      { to: "/calculator", label: "Calculators" },
      { to: "/news", label: "News" },
      { to: "/quarterly", label: "Quarterly" },
      { to: "/ai", label: "AI Assistant" },
    ],
  },
  {
    group: "Reference",
    items: [
      { to: "/securities", label: "Securities" },
      { to: "/brokers", label: "Brokers" },
      { to: "/funds", label: "Funds" },
    ],
  },
];

const THEME_ORDER: ThemePreference[] = ["light", "dark", "system"];

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  const { preference, resolved, setPreference } = useTheme();
  const location = useLocation();
  const [navOpen, setNavOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);

  // Close the mobile drawer whenever the route changes.
  useEffect(() => setNavOpen(false), [location.pathname]);

  // Ctrl+K / Cmd+K opens the palette from anywhere, including inside inputs.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const { data: status } = useQuery({
    queryKey: ["market-status"],
    queryFn: ({ signal }) => market.overview(signal),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  const { data: coverage } = useQuery({
    queryKey: ["coverage"],
    queryFn: ({ signal }) => archive.coverage(signal),
    staleTime: 60_000,
  });

  const open = status?.status.is_open;

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <aside className={`sidebar ${navOpen ? "sidebar-open" : ""}`}>
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <span className="brand-text">
            <strong>Smart Analytics</strong>
            <small>NEPSE</small>
          </span>
        </div>

        <nav className="nav" aria-label="Main">
          {NAV.map((section) => (
            <div className="nav-group" key={section.group}>
              <div className="nav-group-label">{section.group}</div>
              {section.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
                >
                  {item.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <div className="sidebar-foot">
          {coverage && (
            <div className="coverage-mini" title={coverage.note}>
              <span className="coverage-label">Archive</span>
              <span className="coverage-value">
                {coverage.sessions} sessions
              </span>
              <span className="coverage-sub">
                {fmtDateTime(coverage.first_session)} → {fmtDateTime(coverage.last_session)}
              </span>
            </div>
          )}
          <a className="nav-link nav-link-quiet" href="/docs" target="_blank" rel="noreferrer">
            API docs
          </a>
        </div>
      </aside>

      <div className="main-col">
        <header className="topbar">
          <button
            type="button"
            className="icon-btn nav-toggle"
            aria-label="Toggle navigation"
            aria-expanded={navOpen}
            onClick={() => setNavOpen((v) => !v)}
          >
            <span className="hamburger" aria-hidden="true" />
          </button>

          <div className="topbar-status">
            <span
              className={`dot ${open === undefined ? "dot-unknown" : open ? "dot-open" : "dot-closed"}`}
              aria-hidden="true"
            />
            <span>
              {open === undefined
                ? "Market status unknown"
                : open
                  ? "Market open"
                  : "Market closed"}
            </span>
            {status?.status.as_of && (
              <span className="topbar-asof">as of {fmtDateTime(status.status.as_of)}</span>
            )}
          </div>

          <div className="topbar-actions">
            <button
              type="button"
              className="btn btn-sm topbar-search"
              onClick={() => setPaletteOpen(true)}
              aria-label="Open command palette"
            >
              <SearchIcon />
              <span>Search</span>
              <kbd className="kbd">Ctrl K</kbd>
            </button>

            <div className="seg-group theme-switch" role="group" aria-label="Theme">
              {THEME_ORDER.map((option) => (
                <button
                  key={option}
                  type="button"
                  className={`seg-btn ${preference === option ? "active" : ""}`}
                  aria-pressed={preference === option}
                  onClick={() => setPreference(option)}
                  title={
                    option === "system"
                      ? `Follow the operating system (currently ${resolved})`
                      : option === "light"
                        ? "Always light"
                        : "Always dark"
                  }
                >
                  {option === "light" && <SunIcon />}
                  {option === "dark" && <MoonIcon />}
                  {option === "system" && <SystemIcon />}
                  <span className="theme-switch-text">{option}</span>
                </button>
              ))}
            </div>

            {user ? (
              <div className="account">
                <span className="account-name" title={user.email}>
                  {user.display_name || user.email}
                </span>
                {user.is_admin && <span className="badge badge-info">admin</span>}
                <button type="button" className="btn btn-sm" onClick={() => void logout()}>
                  Sign out
                </button>
              </div>
            ) : (
              <NavLink to="/signin" className="btn btn-sm btn-primary">
                Sign in
              </NavLink>
            )}
          </div>
        </header>

        <IndexBar />
        <HighlightsTicker />

        <main className="content" id="main">
          {children}
        </main>

        <footer className="footer">
          <span>Data: Nepal Stock Exchange. Not financial advice.</span>
          <span className="footer-note">
            Missing values are labelled with their reason, never shown as zero.
          </span>
        </footer>
      </div>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}

function SearchIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="11" cy="11" r="7" />
      <path d="M20 20l-3.5-3.5" strokeLinecap="round" />
    </svg>
  );
}

function SystemIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="2" y="4" width="20" height="13" rx="2" />
      <path d="M8 21h8" strokeLinecap="round" />
    </svg>
  );
}

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <circle cx="12" cy="12" r="4" fill="currentColor" />
      <g stroke="currentColor" strokeWidth="2" strokeLinecap="round">
        <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4" />
      </g>
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <path
        d="M20 14.5A8.5 8.5 0 019.5 4a8.5 8.5 0 1010.5 10.5z"
        fill="currentColor"
      />
    </svg>
  );
}
