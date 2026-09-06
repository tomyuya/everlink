import { NextResponse } from "next/server";

import { errorResponse } from "@/lib/api";
import { isReadonly } from "@/lib/db";
import { cronOverview, requestRun } from "@/lib/queries";

export const dynamic = "force-dynamic";

/**
 * POST /api/settings/run-now
 *
 * Stamps a run-now request the NEXT cron fire consumes (and clears). Gated on
 * the heartbeat precondition: without a Railway cron firing at least hourly
 * there is nothing to consume the request, so we refuse honestly (409) instead
 * of pretending a run will start.
 */
export async function POST() {
  try {
    if (isReadonly()) {
      return NextResponse.json({ error: "Board is in read-only mode" }, { status: 403 });
    }
    const overview = await cronOverview();
    if (!overview.heartbeat_alive) {
      return NextResponse.json(
        {
          error:
            "cron heartbeat not alive: no cron fire in the last 75 minutes. " +
            "Set the Railway cron to `0 * * * *` (see the checklist on /settings), " +
            "then run-now becomes available.",
          heartbeat_alive: false,
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
