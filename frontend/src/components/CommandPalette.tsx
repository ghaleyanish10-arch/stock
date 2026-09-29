/* Command palette (Ctrl+K / Cmd+K).
 *
 * One keyboard entry point for navigation and symbol lookup. Symbol search is
 * served from the cached security master already loaded by the app, so opening
 * the palette never triggers a network request.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { reference } from "../api";

interface Command {
  id: string;
  label: string;
  hint: string;
  run: () => void;
}

const PAGES: { to: string; label: string; hint: string }[] = [
  { to: "/", label: "Market overview", hint: "Index, turnover, session totals" },
  { to: "/movers", label: "Movers", hint: "Top gainers and losers" },
  { to: "/stocks", label: "Stocks", hint: "All traded instruments" },
  { to: "/archive", label: "Archive", hint: "Stored history and coverage" },
  { to: "/analytics", label: "Technical", hint: "Indicators for a symbol" },
  { to: "/securities", label: "Securities", hint: "Security master" },
  { to: "/brokers", label: "Brokers", hint: "Official member registry" },
  { to: "/funds", label: "Funds", hint: "Mutual funds and NAV status" },
  { to: "/treemap", label: "Heatmap", hint: "Treemap and sector breakdown" },
  { to: "/screener", label: "Screener", hint: "Filter price, volume, technicals" },
  { to: "/signin", label: "Sign in", hint: "Create or open an account" },
];

export function CommandPalette({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [term, setTerm] = useState("");
  const [highlight, setHighlight] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  // Fetched lazily, only while the palette is open.
  const { data: securities } = useQuery({
    queryKey: ["securities"],
    queryFn: ({ signal }) => reference.securities(undefined, true, signal),
    staleTime: 5 * 60_000,
    enabled: open,
  });

  const close = useCallback(() => {
    onClose();
    setTerm("");
    setHighlight(0);
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
  }, [open]);

  const commands = useMemo<Command[]>(() => {
    const needle = term.trim().toLowerCase();
    const out: Command[] = [];

    for (const page of PAGES) {
      if (needle && !page.label.toLowerCase().includes(needle)) continue;
      out.push({
        id: `page:${page.to}`,
        label: page.label,
        hint: page.hint,
        run: () => navigate(page.to),
      });
    }

    const rows = securities?.securities ?? [];
    for (const s of rows) {
      const name = s.name ?? "";
      if (needle) {
        const match = s.symbol.toLowerCase().includes(needle) || name.toLowerCase().includes(needle);
        if (!match) continue;
      } else {
        // With no query, offering 568 symbols would bury the navigation.
        break;
      }
      out.push({
        id: `sym:${s.symbol}`,
        label: s.symbol,
        hint: name || "Security",
        run: () => navigate(`/chart/${s.symbol}`),
      });
    }
    return out.slice(0, 40);
  }, [term, securities, navigate]);

  // Keep the highlight in range as the result set changes.
  useEffect(() => setHighlight((h) => Math.min(h, Math.max(commands.length - 1, 0))), [commands.length]);

  if (!open) return null;

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => (h + 1) % Math.max(commands.length, 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => (h - 1 + Math.max(commands.length, 1)) % Math.max(commands.length, 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const picked = commands[highlight];
      if (picked) {
        picked.run();
        close();
      }
    }
  };

  return (
    <div className="palette-backdrop" onClick={close} role="presentation">
      <div
        className="palette"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          ref={inputRef}
          className="palette-input"
          value={term}
          onChange={(e) => {
            setTerm(e.target.value);
            setHighlight(0);
          }}
          onKeyDown={onKeyDown}
          placeholder="Jump to a page, or search a symbol…"
          aria-label="Command palette search"
        />

        <ul className="palette-list" role="listbox">
          {commands.length === 0 && (
            <li className="palette-empty">
              {term ? `No match for “${term}”.` : "Type a symbol to search the security master."}
            </li>
          )}
          {commands.map((c, i) => (
            <li key={c.id}>
              <button
                type="button"
                role="option"
                aria-selected={i === highlight}
                className={`palette-item ${i === highlight ? "active" : ""}`}
                onMouseEnter={() => setHighlight(i)}
                onClick={() => {
                  c.run();
                  close();
                }}
              >
                <span className="palette-label">{c.label}</span>
                <span className="palette-hint">{c.hint}</span>
              </button>
            </li>
          ))}
        </ul>

        <div className="palette-foot">
          <span>↑↓ move</span>
          <span>↵ open</span>
          <span>esc close</span>
          <span className="palette-foot-quiet">
            {securities ? `${securities.count} symbols indexed` : "loading symbols…"}
          </span>
        </div>
      </div>
    </div>
  );
}
