// Issues a short-lived LiveKit token only after the service verifies that the
// caller is a participant of this active, unblocked session. Knowing the room
// name is never enough to join.
import { currentUserId } from "@/lib/server/auth";
import { getService } from "@/lib/server/runtime";
import { isAppError } from "@/lib/server/service";

const STATUS: Record<string, number> = { unauthenticated: 401, forbidden: 403, not_found: 404, conflict: 409, not_configured: 501, unavailable: 409, suspended: 403 };

export async function POST(_req: Request, ctx: RouteContext<"/api/sessions/[id]/token">) {
  const { id } = await ctx.params;
  const uid = await currentUserId();
  const found = uid ? await getService().viewerFor(uid) : null;
  if (!found) return Response.json({ error: "Please sign in." }, { status: 401 });
  try {
    const t = await getService().callToken(found.viewer, id);
    return Response.json(t, { headers: { "Cache-Control": "no-store" } });
  } catch (e) {
    if (isAppError(e)) return Response.json({ error: e.message, code: e.code }, { status: STATUS[e.code] ?? 400 });
    throw e;
  }
}
