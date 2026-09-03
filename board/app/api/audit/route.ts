import { NextResponse } from "next/server";

import { errorResponse } from "@/lib/api";
import { listAudit } from "@/lib/queries";

export const dynamic = "force-dynamic";

/** GET /api/audit?limit=100 — the append-only audit trail, newest first. */
export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const raw = Number(url.searchParams.get("limit") ?? 100);
    const limit = Number.isFinite(raw) ? Math.min(500, Math.max(1, raw)) : 100;
    const rows = await listAudit(limit);
    return NextResponse.json({ audit: rows });
  } catch (e) {
    return errorResponse(e);
  }
}
