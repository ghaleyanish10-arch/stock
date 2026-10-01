/* Small shared UI pieces used across pages. */

import React, { type ReactNode, useState, useEffect, useRef } from "react";
import { ApiError } from "../api";
import type { Measured, ValueStatus } from "../types";

const STATUS_LABEL: Record<ValueStatus, string> = {
  ok: "",
  declared_zero: "Declared as zero",
  not_reported: "Not declared yet",
  not_published: "Not published by source",
  upstream_unavailable: "Data unavailable",
  not_applicable: "Not applicable",
  pending: "Not declared yet",
};

function getStatusLabel(status: ValueStatus): string {
  return STATUS_LABEL[status] ?? status;
}

export function ProvenanceChip({
  measured,
  formatter,
}: {
  measured: Measured;
  formatter?: (v: number) => string;
}) {
  const { value, status, note, as_of } = measured;
  const label = getStatusLabel(status);
  const display = value != null ? (formatter ? formatter(value) : String(value)) : label;

  return (
    <span
      className={`mv-chip mv-chip-inline st-${status}`}
      title={note ?? as_of ? `${note ?? ""}${as_of ? ` (as of ${as_of})` : ""}` : label}
    >
      {display}
    </span>
  );
}

export function Missing({ reason }: { reason: string }) {
  return (
    <span className="mv mv-missing" title={reason}>
      {reason}
    </span>
  );
}

export function Card({
  title,
  actions,
  children,
  padded = true,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  padded?: boolean;
}) {
  return (
    <section className="card">
      {(title || actions) && (
        <header className="card-head">
          <h2 className="card-title">{title}</h2>
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      <div className={padded ? "card-body" : "card-body card-body-flush"}>{children}</div>
    </section>
  );
}

export function Stat({
  label,
  hint,
  value,
  children,
}: {
  label: string;
  hint?: string;
  value?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value ?? children}</span>
      {hint && <span className="stat-hint">{hint}</span>}
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="state state-loading" role="status">
      <span className="spinner" aria-hidden="true" />
      <span>{label}…</span>
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
  const message = error instanceof Error ? error.message : "Something went wrong.";
  const status = error instanceof ApiError ? error.status : 0;
  
  let title = "Request failed";
  let isAuthError = false;
  
  if (status === 401) {
    title = "Please sign in";
    isAuthError = true;
  } else if (status === 404) {
    title = "Not found";
  } else if (status >= 500) {
    title = "Server error";
  } else if (status >= 400) {
    title = "Request failed";
  } else if (status === 0) {
    title = "Network error";
  }
  
  const isTransient = status === 0 || status >= 500 || status === 429;
  
  return (
    <div className="state state-error" role="alert">
      <strong>{isTransient ? "Temporarily unavailable" : title}</strong>
      <span>{message}</span>
      {isAuthError && (
        <p className="muted" style={{ marginTop: "var(--space-2)" }}>
          You need to be signed in to access this page.
        </p>
      )}
      {onRetry && !isAuthError && (
        <button type="button" className="btn btn-sm" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="state state-empty">
      <span>{message}</span>
    </div>
  );
}

export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "up" | "down" | "warn" | "info" | "ok";
  children: ReactNode;
}) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function Toolbar({ children }: { children: ReactNode }) {
  return <div className="toolbar">{children}</div>;
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}

export interface Column<T> {
  key: string;
  header: ReactNode;
  align?: "left" | "right" | "center";
  /** Custom cell renderer; falls back to reading `row[key]`. */
  render?: (row: T) => ReactNode;
}

export interface VirtualizedTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  empty: string;
  rowHeight?: number;
  overscan?: number;
}

export function VirtualizedTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  empty,
  rowHeight = 40,
  overscan = 5,
}: VirtualizedTableProps<T>) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [containerHeight, setContainerHeight] = useState(400);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerHeight(entry.contentRect.height);
      }
    });
    resizeObserver.observe(el);
    return () => resizeObserver.disconnect();
  }, []);

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    setScrollTop(e.currentTarget.scrollTop);
  };

  const visibleCount = Math.ceil(containerHeight / rowHeight) + overscan * 2;
  const startIndex = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan);
  const endIndex = Math.min(rows.length, startIndex + visibleCount);
  const visibleRows = rows.slice(startIndex, endIndex);
  const offsetY = startIndex * rowHeight;

  if (rows.length === 0) return <EmptyState message={empty} />;

  return (
    <div
      ref={containerRef}
      className="table-wrap"
      style={{ height: containerHeight, overflow: "auto" }}
      onScroll={handleScroll}
      role="region"
      aria-label="Data table"
      tabIndex={0}
    >
      <table className="table" role="grid">
        <thead>
          <tr role="row">
            {columns.map((c) => (
              <th
                key={c.key}
                className={c.align ? `align-${c.align}` : undefined}
                scope="col"
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody style={{ transform: `translateY(${offsetY}px)` }}>
          {visibleRows.map((row) => (
            <tr
              key={rowKey(row)}
              className={onRowClick ? "clickable" : undefined}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              role="row"
              tabIndex={onRowClick ? 0 : -1}
              onKeyDown={onRowClick ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onRowClick(row); }} : undefined}
            >
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={c.align ? `align-${c.align}` : undefined}
                  role="gridcell"
                >
                  {c.render
                    ? c.render(row)
                    : ((row as Record<string, ReactNode>)[c.key] ?? null)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Modal({
  isOpen,
  onClose,
  title,
  children,
  size = "md",
}: {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
}) {
  if (!isOpen) return null;

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  return (
    <div
      className="modal-overlay"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="modal-title"
    >
      <div
        className={`modal modal-${size}`}
        onClick={(e) => e.stopPropagation()}
        role="document"
      >
        <header className="modal-header">
          <h2 id="modal-title" className="modal-title">{title}</h2>
          <button
            type="button"
            className="modal-close"
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </header>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

export function Pagination({
  currentPage,
  totalPages,
  onPageChange,
}: {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}) {
  if (totalPages <= 1) return null;

  const pages: (number | string)[] = [];
  const maxVisible = 5;
  let start = Math.max(1, currentPage - Math.floor(maxVisible / 2));
  let end = Math.min(totalPages, start + maxVisible - 1);

  if (end - start + 1 < maxVisible) {
    start = Math.max(1, end - maxVisible + 1);
  }

  if (start > 1) {
    pages.push(1);
    if (start > 2) pages.push("...");
  }

  for (let i = start; i <= end; i++) {
    pages.push(i);
  }

  if (end < totalPages) {
    if (end < totalPages - 1) pages.push("...");
    pages.push(totalPages);
  }

  return (
    <nav className="pagination" aria-label="Pagination">
      <button
        className="pagination-btn"
        onClick={() => onPageChange(currentPage - 1)}
        disabled={currentPage === 1}
        aria-label="Previous page"
      >
        ‹
      </button>
      {pages.map((page, i) =>
        page === "..." ? (
          <span key={`ellipsis-${i}`} className="pagination-ellipsis">…</span>
        ) : (
          <button
            key={i}
            className={`pagination-btn ${page === currentPage ? "active" : ""}`}
            onClick={() => onPageChange(page as number)}
            aria-current={page === currentPage ? "page" : undefined}
            aria-label={`Page ${page}`}
          >
            {page}
          </button>
        )
      )}
      <button
        className="pagination-btn"
        onClick={() => onPageChange(currentPage + 1)}
        disabled={currentPage === totalPages}
        aria-label="Next page"
      >
        ›
      </button>
    </nav>
  );
}

export function Button({
  children,
  onClick,
  type = "button",
  variant = "primary",
  disabled = false,
  loading = false,
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  type?: "button" | "submit" | "reset";
  variant?: "primary" | "secondary" | "danger" | "outline" | "ghost";
  disabled?: boolean;
  loading?: boolean;
  className?: string;
}) {
  return (
    <button
      type={type}
      className={`btn btn-${variant} ${className}`}
      onClick={onClick}
      disabled={disabled || loading}
    >
      {loading && <span className="spinner-sm" aria-hidden="true" />}
      <span>{loading ? "Loading" : children}</span>
    </button>
  );
}

export function Input({
  value,
  onChange,
  type = "text",
  placeholder,
  error,
  disabled = false,
  className = "",
  ...props
}: React.InputHTMLAttributes<HTMLInputElement> & {
  error?: string;
  className?: string;
}) {
  return (
    <div className="input-wrapper">
      <input
        type={type}
        value={value}
        onChange={(e: React.ChangeEvent<HTMLInputElement>) => onChange?.(e)}
        placeholder={placeholder}
        disabled={disabled}
        className={`form-input ${error ? "error" : ""} ${className}`}
        {...props}
      />
      {error && <span className="input-error">{error}</span>}
    </div>
  );
}

export function Select({
  value,
  onChange,
  options,
  placeholder,
  error,
  disabled = false,
  className = "",
}: {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  placeholder?: string;
  error?: string;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <div className="select-wrapper">
      <select
        value={value}
        onChange={(e: React.ChangeEvent<HTMLSelectElement>) => onChange(e.target.value)}
        disabled={disabled}
        className={`form-select ${error ? "error" : ""} ${className}`}
      >
        {placeholder && <option value="" disabled>{placeholder}</option>}
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      {error && <span className="input-error">{error}</span>}
    </div>
  );
}

export function Alert({
  children,
  type = "info",
  onDismiss,
}: {
  children: ReactNode;
  type?: "info" | "error" | "success" | "warning";
  onDismiss?: () => void;
}) {
  const [visible, setVisible] = useState(true);
  if (!visible) return null;

  return (
    <div className={`alert alert-${type}`} role="alert">
      <span>{children}</span>
      {onDismiss && (
        <button type="button" className="alert-dismiss" onClick={() => setVisible(false)} aria-label="Dismiss">
          ×
        </button>
      )}
    </div>
  );
}

export function Textarea({
  value,
  onChange,
  rows = 3,
  placeholder,
  className = "",
  ...props
}: React.TextareaHTMLAttributes<HTMLTextAreaElement> & {
  className?: string;
}) {
  return (
    <textarea
      value={value}
      onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => onChange?.(e)}
      rows={rows}
      placeholder={placeholder}
      className={`form-textarea ${className}`}
      {...props}
    />
  );
}

export interface Column<T> {
  key: string;
  header: ReactNode;
  align?: "left" | "right" | "center";
  /** Custom cell renderer; falls back to reading `row[key]`. */
  render?: (row: T) => ReactNode;
}

export function Table<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  empty,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  empty: string;
}) {
  // Use virtualized table for large datasets
  if (rows.length > 100) {
    return <VirtualizedTable columns={columns} rows={rows} rowKey={rowKey} onRowClick={onRowClick} empty={empty} />;
  }
  
  if (rows.length === 0) return <EmptyState message={empty} />;
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={c.align ? `align-${c.align}` : undefined}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              className={onRowClick ? "clickable" : undefined}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
            >
              {columns.map((c) => (
                <td key={c.key} className={c.align ? `align-${c.align}` : undefined}>
                  {c.render
                    ? c.render(row)
                    : ((row as Record<string, ReactNode>)[c.key] ?? null)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}