"use client";

import React from "react";
import { AlertTriangle, Loader2, SearchX, X } from "lucide-react";

export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`rounded-2xl border border-line bg-white shadow-card ${className}`}>{children}</div>;
}

export function PageHeader({
  eyebrow,
  title,
  subtitle,
  actions,
}: {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div>
        {eyebrow && (
          <p className="mb-1 font-mono text-[11px] font-semibold uppercase tracking-[0.14em] text-primary">{eyebrow}</p>
        )}
        <h1 className="text-[22px] font-bold tracking-tight text-ink sm:text-[26px]">{title}</h1>
        {subtitle && <p className="mt-1 max-w-2xl text-sm text-ink-soft">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function StatCard({
  icon,
  label,
  value,
  sub,
  tone = "primary",
}: {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  sub?: React.ReactNode;
  tone?: "primary" | "success" | "warn" | "danger" | "neutral";
}) {
  const tones: Record<string, string> = {
    primary: "bg-primary-soft text-primary",
    success: "bg-success-soft text-success",
    warn: "bg-warn-soft text-warn",
    danger: "bg-danger-soft text-danger",
    neutral: "bg-surface-container text-ink-soft",
  };
  return (
    <Card className="p-4">
      <div className="flex items-start gap-3">
        <span className={`rounded-xl p-2.5 ${tones[tone]}`}>{icon}</span>
        <div className="min-w-0">
          <p className="font-mono text-[22px] font-semibold leading-tight tracking-tight text-ink">{value}</p>
          <p className="mt-0.5 text-[13px] font-medium text-ink-soft">{label}</p>
          {sub && <p className="mt-1 text-[11px] text-ink-muted">{sub}</p>}
        </div>
      </div>
    </Card>
  );
}

const STATUS_STYLES: Record<string, string> = {
  online: "bg-success-soft text-success ring-success/20",
  offline: "bg-surface-container text-ink-muted ring-line",
  connecting: "bg-warn-soft text-warn ring-warn/20",
  reconnecting: "bg-warn-soft text-warn ring-warn/20",
  error: "bg-danger-soft text-danger ring-danger/20",
  queued: "bg-warn-soft text-warn ring-warn/20",
  processing: "bg-primary-soft text-primary ring-primary/20",
  ready: "bg-success-soft text-success ring-success/20",
  failed: "bg-danger-soft text-danger ring-danger/20",
  cancelled: "bg-surface-container text-ink-muted ring-line",
};

const STATUS_DOT: Record<string, string> = {
  online: "bg-emerald-500",
  connecting: "bg-amber-500",
  reconnecting: "bg-amber-500",
  error: "bg-rose-500",
  processing: "bg-primary",
  queued: "bg-amber-500",
  ready: "bg-emerald-500",
  failed: "bg-rose-500",
};

export function StatusPill({ status, label }: { status: string; label?: string }) {
  const style = STATUS_STYLES[status] || STATUS_STYLES.offline;
  const dot = STATUS_DOT[status] || "bg-slate-400";
  const live = status === "online";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold capitalize ring-1 ${style}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${dot} ${live ? "live-dot" : ""}`} />
      {label || status.replace(/_/g, " ")}
    </span>
  );
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "primary" | "success" | "warn" | "danger";
}) {
  const tones: Record<string, string> = {
    neutral: "bg-surface-container text-ink-soft",
    primary: "bg-primary-soft text-primary",
    success: "bg-success-soft text-success",
    warn: "bg-warn-soft text-warn",
    danger: "bg-danger-soft text-danger",
  };
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wide ${tones[tone]}`}>
      {children}
    </span>
  );
}

export function ScoreBar({ score, label = true }: { score: number; label?: boolean }) {
  const pct = Math.min(100, Math.max(0, Math.round(score * 100)));
  const colour = pct >= 30 ? "bg-success" : pct >= 24 ? "bg-primary" : "bg-ink-muted";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-surface-high">
        <div className={`h-full rounded-full ${colour}`} style={{ width: `${pct}%` }} />
      </div>
      {label && <span className="font-mono text-[11px] tabular-nums text-ink-soft">{pct}%</span>}
    </div>
  );
}

export function ProgressBar({ value, className = "" }: { value: number; className?: string }) {
  return (
    <div className={`h-1.5 w-full overflow-hidden rounded-full bg-surface-high ${className}`}>
      <div className="h-full rounded-full bg-primary transition-all duration-500" style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-ink-muted">
      <Loader2 className="h-7 w-7 animate-spin text-primary" />
      {label && <p className="text-sm">{label}</p>}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton rounded-xl ${className}`} />;
}

export function EmptyState({
  title,
  message,
  icon,
  action,
}: {
  title: string;
  message?: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-line bg-white/70 px-6 py-12 text-center">
      <div className="rounded-2xl bg-surface-container p-3 text-ink-muted">{icon ?? <SearchX className="h-7 w-7" />}</div>
      <div>
        <p className="font-semibold text-ink">{title}</p>
        {message && <p className="mx-auto mt-1 max-w-md text-sm text-ink-soft">{message}</p>}
      </div>
      {action}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-danger/20 bg-danger-soft/50 px-6 py-10 text-center">
      <AlertTriangle className="h-7 w-7 text-danger" />
      <p className="max-w-lg text-sm font-medium text-danger">{message}</p>
      {onRetry && (
        <button onClick={onRetry} className={btnSecondary}>
          Try again
        </button>
      )}
    </div>
  );
}

export function Modal({
  open,
  onClose,
  title,
  subtitle,
  children,
  wide,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  wide?: boolean;
}) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center overflow-y-auto bg-ink/50 p-0 backdrop-blur-sm sm:items-center sm:p-4"
      onClick={onClose}
    >
      <div
        className={`max-h-[92vh] w-full overflow-y-auto rounded-t-3xl bg-white shadow-float sm:rounded-3xl ${
          wide ? "sm:max-w-4xl" : "sm:max-w-xl"
        }`}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-line bg-white/95 px-5 py-4 backdrop-blur">
          <div>
            <h3 className="font-semibold text-ink">{title}</h3>
            {subtitle && <p className="mt-0.5 text-xs text-ink-muted">{subtitle}</p>}
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-ink-muted transition hover:bg-surface-container hover:text-ink" aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
      </div>
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[13px] font-semibold text-ink-soft">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] leading-relaxed text-ink-muted">{hint}</span>}
    </label>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  hint,
  disabled,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  hint?: string;
  disabled?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div>
        <p className="text-[13px] font-semibold text-ink-soft">{label}</p>
        {hint && <p className="text-[11px] text-ink-muted">{hint}</p>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative h-6 w-11 shrink-0 rounded-full transition-colors disabled:opacity-50 ${
          checked ? "bg-primary" : "bg-slate-300"
        }`}
      >
        <span
          className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow-sm transition-transform ${
            checked ? "translate-x-[22px]" : "translate-x-0.5"
          }`}
        />
      </button>
    </div>
  );
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  size = "md",
}: {
  options: { value: T; label: string; icon?: React.ReactNode }[];
  value: T;
  onChange: (value: T) => void;
  size?: "sm" | "md";
}) {
  return (
    <div className="inline-flex rounded-xl border border-line bg-surface-low p-1">
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(option.value)}
            className={`inline-flex items-center gap-1.5 rounded-lg font-semibold transition ${
              size === "sm" ? "px-2.5 py-1.5 text-[11px]" : "px-3 py-1.5 text-xs"
            } ${active ? "bg-white text-ink shadow-card" : "text-ink-soft hover:text-ink"}`}
          >
            {option.icon}
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

export const inputCls =
  "w-full rounded-xl border border-line bg-white px-3 py-2.5 text-sm text-ink placeholder:text-ink-muted/70 outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/15";

export const selectCls =
  "w-full appearance-none rounded-xl border border-line bg-white px-3 py-2.5 text-sm text-ink outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/15";

export const btnPrimary =
  "inline-flex items-center justify-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-primary-strong disabled:cursor-not-allowed disabled:opacity-50";

export const btnSecondary =
  "inline-flex items-center justify-center gap-2 rounded-xl border border-line bg-white px-4 py-2.5 text-sm font-semibold text-ink-soft transition hover:border-primary/40 hover:bg-surface-low disabled:cursor-not-allowed disabled:opacity-50";

export const btnGhost =
  "inline-flex items-center justify-center gap-2 rounded-xl px-3 py-2 text-sm font-medium text-ink-soft transition hover:bg-surface-container disabled:opacity-50";

export const btnDanger =
  "inline-flex items-center justify-center gap-2 rounded-xl border border-danger/20 bg-white px-4 py-2.5 text-sm font-semibold text-danger transition hover:bg-danger-soft disabled:opacity-50";
