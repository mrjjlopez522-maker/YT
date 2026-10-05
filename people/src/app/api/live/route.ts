// Demo-mode live updates over server-sent events. Each topic is authorised:
// "user:<id>" only for yourself, "session:<id>" only for its participants.
// Events carry no data — clients re-fetch through authorised server paths.
import { serverConfig } from "@/lib/config";
import { currentUserId } from "@/lib/server/auth";
import { bus } from "@/lib/server/events";
import { getService } from "@/lib/server/runtime";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  if (serverConfig().mode !== "demo") return new Response("Use Supabase Realtime in live mode.", { status: 404 });
  const uid = await currentUserId();
  const found = uid ? await getService().viewerFor(uid) : null;
  if (!found) return new Response("Unauthorized", { status: 401 });
  const requested = new URL(req.url).searchParams.getAll("t").slice(0, 5);
  const allowed: string[] = [];
  for (const t of requested) {
    if (t === `user:${uid}`) allowed.push(t);
    else if (t.startsWith("session:")) {
      try {
        await getService().getSession(found.viewer, t.slice(8));
        allowed.push(t);
      } catch { /* not a participant: silently ignored */ }
    }
  }
  const enc = new TextEncoder();
  let cleanup = () => {};
  const stream = new ReadableStream({
    start(controller) {
      const send = (s: string) => { try { controller.enqueue(enc.encode(s)); } catch { cleanup(); } };
      const onChange = (topic: string) => { if (allowed.includes(topic)) send(`data: ${JSON.stringify({ topic })}\n\n`); };
      bus.on("change", onChange);
      const ping = setInterval(() => send(": ping\n\n"), 20_000);
      cleanup = () => { bus.off("change", onChange); clearInterval(ping); };
      send(`event: ready\ndata: ${JSON.stringify({ topics: allowed })}\n\n`);
      req.signal.addEventListener("abort", () => { cleanup(); try { controller.close(); } catch {} });
    },
    cancel() { cleanup(); },
  });
  return new Response(stream, { headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache, no-transform", Connection: "keep-alive" } });
}
