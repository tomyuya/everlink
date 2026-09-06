import { NextResponse } from "next/server";

import { errorResponse } from "@/lib/api";
import { isReadonly } from "@/lib/db";
import { updateSettings } from "@/lib/queries";

export const dynamic = "force-dynamic";

/**
 * POST /api/settings  { rotation_cycle_days?, run_hour_utc?, enabled? }
 *
 * The operator knobs of the autonomous loop (rotation cycle, which hourly
 * heartbeat runs the chain, cron kill-switch). Every change is audited into
 * `audit_log` as `settings_change`. Read-only demo boards get 403.
 */
export async function POST(request: Request) {
  try {
    if (isReadonly()) {
      return NextResponse.json({ error: "Board is in read-only mode" }, { status: 403 });
    }
    const body = await request.json().catch(() => ({}));
    const patch: {
      rotation_cycle_days?: number;
      run_hour_utc?: number;
      enabled?: boolean;
    } = {};

    if (body.rotation_cycle_days !== undefined) {
      const v = Number(body.rotation_cycle_days);
      if (!Number.isInteger(v) || v < 7 || v > 120) {
        return NextResponse.json(
          { error: "rotation_cycle_days must be an integer between 7 and 120" },
          { status: 400 },
        );
      }
      patch.rotation_cycle_days = v;
    }
    if (body.run_hour_utc !== undefined) {
      const v = Number(body.run_hour_utc);
      if (!Number.isInteger(v) || v < 0 || v > 23) {
        return NextResponse.json(
          { error: "run_hour_utc must be an integer between 0 and 23" },
          { status: 400 },
        );
      }
      patch.run_hour_utc = v;
    }
    if (body.enabled !== undefined) {
      if (typeof body.enabled !== "boolean") {
        return NextResponse.json({ error: "enabled must be a boolean" }, { status: 400 });
      }
      patch.enabled = body.enabled;
    }
    if (Object.keys(patch).length === 0) {
      return NextResponse.json(
        { error: "nothing to update: send rotation_cycle_days, run_hour_utc and/or enabled" },
        { status: 400 },
      );
    }

    const settings = await updateSettings(patch, "board");
    return NextResponse.json({ ok: true, settings });
  } catch (e) {
    return errorResponse(e);
  }
}
