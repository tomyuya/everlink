import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

import type { Action, DecisionStatus, RiskLevel, Verdict } from "./types";

/** Tailwind-aware className merge (the user's stack convention). */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Parse a JSON column that may already be an object/array or a TEXT string. */
export function safeJsonParse<T>(value: unknown, fallback: T): T {
  if (value == null) return fallback;
  if (typeof value !== "string") return value as T;
  try {
    return JSON.parse(value) as T;
  } catch {
    return fallback;
  }
}

export const STATUS_META: Record<DecisionStatus, { label: string; className: string }> = {
  pending: { label: "Pending", className: "bg-amber-500/15 text-amber-700 dark:text-amber-400 ring-amber-500/30" },
  approved: { label: "Approved", className: "bg-sky-500/15 text-sky-700 dark:text-sky-400 ring-sky-500/30" },
  applied: { label: "Applied", className: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 ring-emerald-500/30" },
  rejected: { label: "Rejected", className: "bg-rose-500/15 text-rose-700 dark:text-rose-400 ring-rose-500/30" },
  expired: { label: "Expired", className: "bg-zinc-500/15 text-zinc-600 dark:text-zinc-400 ring-zinc-500/30" },
};

export const RISK_META: Record<RiskLevel, { label: string; className: string }> = {
  low: { label: "Low risk", className: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 ring-emerald-500/30" },
  medium: { label: "Medium risk", className: "bg-amber-500/15 text-amber-700 dark:text-amber-400 ring-amber-500/30" },
  high: { label: "High risk", className: "bg-rose-500/15 text-rose-700 dark:text-rose-400 ring-rose-500/30" },
};

export const ACTION_LABEL: Record<Action, string> = {
  REPLACE_URL: "Replace URL",
  REWRITE_ANCHOR: "Rewrite anchor",
  REWRITE_SENTENCE: "Rewrite sentence",
  DROP_BLOCK: "Drop block",
  ESCALATE_HUMAN: "Escalate to human",
};

export const VERDICT_META: Record<Verdict, { label: string; className: string }> = {
  healthy: { label: "Healthy", className: "text-emerald-600 dark:text-emerald-400" },
  dead: { label: "Dead", className: "text-rose-600 dark:text-rose-400" },
  offer_changed: { label: "Offer changed", className: "text-amber-600 dark:text-amber-400" },
  program_ended: { label: "Program ended", className: "text-orange-600 dark:text-orange-400" },
  needs_human_recheck: { label: "Needs recheck", className: "text-sky-600 dark:text-sky-400" },
};

/** Compact relative time (e.g. "3h ago"); falls back to "" for null/invalid. */
export function relativeTime(iso?: string | null): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const secs = Math.round((Date.now() - then) / 1000);
  if (secs < 60) return "just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return `${new Date(iso).toISOString().slice(0, 10)} UTC`;
}

/**
 * Absolute timestamp, always rendered in UTC with an explicit zone suffix
 * ("2026-09-04 23:27:55 UTC"). The product runs on a UTC cron against a UTC
 * database while viewers sit in many zones, so local-time rendering was
 * ambiguous — every absolute time on the board carries its zone.
 */
export function formatDateTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const [day, time] = d.toISOString().split(".")[0].split("T");
  return `${day} ${time} UTC`;
}
