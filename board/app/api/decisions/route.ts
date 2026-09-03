import { NextResponse } from "next/server";

import { errorResponse } from "@/lib/api";
import { batchDecide, listDecisions, statusCounts } from "@/lib/queries";
import type { DecisionStatus } from "@/lib/types";

export const dynamic = "force-dynamic";

const VALID = new Set(["pending", "approved", "applied", "rejected", "expired", "all"]);

/**
 * GET /api/decisions?status=pending&limit=100
 * Returns `{ counts, decisions }` — the exact shape the Python CLI's
 * `decisions --json` emits, so the board and the CLI are interchangeable clients.
 */
export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const raw = url.searchParams.get("status") ?? "pending";
    const status = (VALID.has(raw) ? raw : "pending") as DecisionStatus | "all";
    const limit = Math.min(500, Math.max(1, Number(url.searchParams.get("limit") ?? 100)));

    const [decisions, counts] = await Promise.all([
      listDecisions(status, Number.isFinite(limit) ? limit : 100),
      statusCounts(),
    ]);
    return NextResponse.json({ counts, decisions });
  } catch (e) {
    return errorResponse(e);
  }
}

/**
 * POST /api/decisions  { ids: string[], action: "approve" | "reject", reason?: string }
 * Batch decision — the board's "approve the low-risk ones at once" path. Scoped to
 * `status = 'pending'` in SQL, so already-settled cards are silently skipped and
 * `changed` reports how many actually moved.
 */
export async function POST(request: Request) {
  try {
    const body = await request.json().catch(() => ({}));
    const ids: string[] = Array.isArray(body?.ids)
      ? body.ids.filter((x: unknown): x is string => typeof x === "string")
      : [];
    const action: "approve" | "reject" = body?.action === "reject" ? "reject" : "approve";
    const reason = typeof body?.reason === "string" ? body.reason : "";

    if (!ids.length) {
      return NextResponse.json({ error: "ids (non-empty array) required" }, { status: 400 });
    }

    const result = await batchDecide(ids, action, reason);
    return NextResponse.json({ ok: true, action, ...result });
  } catch (e) {
    return errorResponse(e);
  }
}
