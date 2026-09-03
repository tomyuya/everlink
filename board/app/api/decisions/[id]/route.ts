import { NextResponse } from "next/server";

import { errorResponse } from "@/lib/api";
import {
  approveDecision,
  getDecisionWithEvidence,
  rejectDecision,
} from "@/lib/queries";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ id: string }> };

/** GET /api/decisions/[id] — the card joined with its slots + latest evidence. */
export async function GET(_request: Request, { params }: Ctx) {
  const { id } = await params;
  try {
    const data = await getDecisionWithEvidence(id);
    if (!data) return NextResponse.json({ error: "not found" }, { status: 404 });
    return NextResponse.json(data);
  } catch (e) {
    return errorResponse(e);
  }
}

/**
 * PATCH /api/decisions/[id]  { action: "approve" | "reject", reason?: string }
 * Single-card decision. Returns 409 when the card is not `pending` (already settled
 * or missing) so a stale tab can never silently re-decide.
 */
export async function PATCH(request: Request, { params }: Ctx) {
  const { id } = await params;
  try {
    const body = await request.json().catch(() => ({}));
    const action: "approve" | "reject" = body?.action === "reject" ? "reject" : "approve";
    const reason = typeof body?.reason === "string" ? body.reason : "";

    const changed =
      action === "approve"
        ? await approveDecision(id)
        : await rejectDecision(id, reason);

    if (!changed) {
      return NextResponse.json(
        { ok: false, error: "decision is not pending (or does not exist)" },
        { status: 409 },
      );
    }
    return NextResponse.json({ ok: true, id, action });
  } catch (e) {
    return errorResponse(e);
  }
}
