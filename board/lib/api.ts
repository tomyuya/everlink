import { NextResponse } from "next/server";

import { BoardDbNotConfigured, BoardWriteRefused } from "./db";

/**
 * Map a thrown error to an honest HTTP response. Configuration/write-guard errors
 * get 503/403 (never a silent 500), everything else degrades to a 500 with the
 * message so the board UI can show why it failed.
 */
export function errorResponse(e: unknown): NextResponse {
  if (e instanceof BoardDbNotConfigured) {
    return NextResponse.json({ error: e.message }, { status: 503 });
  }
  if (e instanceof BoardWriteRefused) {
    return NextResponse.json({ error: e.message }, { status: 403 });
  }
  const message = e instanceof Error ? e.message : "Internal error";
  return NextResponse.json({ error: message }, { status: 500 });
}
