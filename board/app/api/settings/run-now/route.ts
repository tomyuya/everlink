import { NextResponse } from "next/server";

import { errorResponse } from "@/lib/api";
import { isReadonly } from "@/lib/db";
import { cronOverview, requestRun } from "@/lib/queries";

export const dynamic = "force-dynamic";

/**
 * POST /api/settings/run-now
 *
 * Stamps a run-now request the NEXT cron fire consumes (and clears). Gated on
 * run_now_available, not mere liveness: a healthy DAILY cron is alive but cannot
 * honour an on-demand run within the hour — the request would sit until the next
 * 03:00 fire — so we refuse honestly (409) and name the real reason instead of
 * pretending a run will start now.
 */
export async function POST() {
  try {
    if (isReadonly()) {
      return NextResponse.json({ error: "Board is in read-only mode" }, { status: 403 });
    }
    const overview = await cronOverview();
    if (!overview.run_now_available) {
      // Three honest reasons, told apart. Only the first reads as a fault; the other
      // two are a healthy cron that simply cannot honour an on-demand "now" yet.
      const error = !overview.heartbeat_alive
        ? "cron heartbeat not alive: no Railway cron fire within the expected window. " +
          "Set the Railway cron to `0 * * * *` (see the checklist on /settings), then " +
          "run-now becomes available."
        : overview.period_min === null
          ? "Your cron is wired and has fired once, but not often enough yet to confirm it " +
            "can pick a run-now up within the hour. It will clarify after the next fire — or " +
            "set the Railway cron to `0 * * * *` (hourly) to enable on-demand runs now."
          : "Your cron fires about once a day, so a run-now request would sit until the next " +
            "daily fire (up to 24h) — it is not really 'now'. Set the Railway cron to " +
            "`0 * * * *` (hourly) to enable on-demand runs; the daily fire already runs the " +
            "chain on schedule.";
      return NextResponse.json(
        {
          error,
          heartbeat_alive: overview.heartbeat_alive,
          run_now_available: false,
          period_min: overview.period_min,
          last_fire_at: overview.last_fire_at,
        },
        { status: 409 },
      );
    }
    const settings = await requestRun("board");
    return NextResponse.json({ ok: true, settings });
  } catch (e) {
    return errorResponse(e);
  }
}
