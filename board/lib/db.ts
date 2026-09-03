/**
 * Board database access — a thin, LAZY wrapper over Neon's serverless HTTP driver.
 *
 * Design notes:
 *  - The client is built on first use (not at import), so `next build` and
 *    `tsc --noEmit` succeed with NO database configured. Pages/routes that need
 *    data call `getSql()` at request time and are marked dynamic.
 *  - The board reads EverLink's OWN operational tables (decisions / slot_checks /
 *    audit_log / link_slots) and its ONLY write is a decision status transition
 *    (pending -> approved | rejected). It never writes source content and never
 *    runs DDL. `assertBoardWritable()` adds a deny-list guard mirroring the Python
 *    `db._assert_writable`, so a misconfigured DSN cannot point the board's writes
 *    at a forbidden host.
 */
import { neon } from "@neondatabase/serverless";

export type Sql = ReturnType<typeof neon>;

export class BoardDbNotConfigured extends Error {
  constructor() {
    super(
      "Board database is not configured. Set EVERLINK_DATABASE_URL (or DATABASE_URL) " +
        "to EverLink's own Postgres. See board/.env.example.",
    );
  }
}

export class BoardWriteRefused extends Error {
  constructor(host: string) {
    super(
      `Refusing to write: the board DSN host '${host}' matches EVERLINK_FORBIDDEN_HOSTS. ` +
        `The board only ever writes decision status transitions to EverLink's OWN database.`,
    );
  }
}

/** EVERLINK_DATABASE_URL first (matches the Python agent), then Vercel's DATABASE_URL. */
export function resolveDsn(): string {
  return process.env.EVERLINK_DATABASE_URL || process.env.DATABASE_URL || "";
}

export function isConfigured(): boolean {
  return resolveDsn().length > 0;
}

/** Bare lowercase host of a DSN (no userinfo, no port). */
export function hostOf(dsn: string): string {
  try {
    return (new URL(dsn).hostname || "").toLowerCase();
  } catch {
    return "";
  }
}

function forbiddenFragments(): string[] {
  return (process.env.EVERLINK_FORBIDDEN_HOSTS || "")
    .split(",")
    .map((f) => f.trim().toLowerCase())
    .filter(Boolean);
}

/**
 * Defense-in-depth guard before any write. Mirrors everlink.db._assert_writable for
 * the explicit deny-list part (the board does not hold the source-site DSNs).
 */
export function assertBoardWritable(): void {
  const dsn = resolveDsn();
  if (!dsn) throw new BoardDbNotConfigured();
  const low = dsn.toLowerCase();
  const host = hostOf(dsn);
  for (const frag of forbiddenFragments()) {
    if (host === frag || low.includes(frag)) throw new BoardWriteRefused(frag);
  }
}

let _sql: Sql | null = null;

/** Lazily build (and cache) the Neon query function. Throws if unconfigured. */
export function getSql(): Sql {
  if (_sql) return _sql;
  const dsn = resolveDsn();
  if (!dsn) throw new BoardDbNotConfigured();
  _sql = neon(dsn);
  return _sql;
}

/** True when the board is served as a read-only public view (demo link). */
export function isReadonly(): boolean {
  return process.env.NEXT_PUBLIC_BOARD_READONLY === "1";
}
