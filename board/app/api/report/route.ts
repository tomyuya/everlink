import { NextResponse } from "next/server";

import { errorResponse } from "@/lib/api";
import { weeklyStats } from "@/lib/queries";

export const dynamic = "force-dynamic";

/**
 * GET /api/report?days=7 — the live weekly aggregate. This is the JSON twin of the
 * /report page and the same numbers pe3's scheduled digest will send out.
 */
export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const raw = Number(url.searchParams.get("days") ?? 7);
    const days = Number.isFinite(raw) ? Math.min(90, Math.max(1, Math.round(raw))) : 7;
    const stats = await weeklyStats(days);
    return NextResponse.json(stats);
  } catch (e) {
    return errorResponse(e);
  }
}
