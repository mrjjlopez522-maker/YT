"use client";

// Live updates. Demo mode: server-sent events from this server. Live mode:
// Supabase Realtime, which only delivers rows the signed-in user may read (RLS).
// Either way the event is just a nudge: the page re-fetches through the server.

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { supabaseBrowser } from "@/lib/supabase/client";
import { usePublicConfig } from "./config-context";
import { cx } from "./ui";

export type LiveStatus = "connecting" | "live" | "reconnecting" | "offline";

const SESSION_TABLES = ["messages", "checklist_items", "shared_notes", "session_participants"] as const;

export function useLive(topics: string[], onChange?: () => void): LiveStatus {
  const router = useRouter();
  const cfg = usePublicConfig();
  const [status, setStatus] = useState<LiveStatus>("connecting");
  const cb = useRef(onChange);
  useEffect(() => { cb.current = onChange; });
  const key = topics.join(",");

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const refresh = () => {
      clearTimeout(timer);
      timer = setTimeout(() => (cb.current ? cb.current() : router.refresh()), 120);
    };
    const list = key.split(",").filter(Boolean);
    let cleanup = () => {};

    if (cfg.mode === "demo") {
      const qs = list.map((t) => `t=${encodeURIComponent(t)}`).join("&");
      const es = new EventSource(`/api/live?${qs}`);
      es.addEventListener("ready", () => setStatus("live"));
      es.onmessage = refresh;
      es.onerror = () => setStatus(navigator.onLine ? "reconnecting" : "offline");
      es.onopen = () => setStatus("live");
      cleanup = () => es.close();
    } else if (cfg.supabaseUrl && cfg.supabaseAnonKey) {
      const sb = supabaseBrowser(cfg.supabaseUrl, cfg.supabaseAnonKey);
      const ch = sb.channel(`live:${key}`);
      for (const t of list) {
        const [kind, id] = t.split(":");
        if (kind === "session") {
          for (const table of SESSION_TABLES)
            ch.on("postgres_changes", { event: "*", schema: "public", table, filter: `session_id=eq.${id}` }, refresh);
          ch.on("postgres_changes", { event: "*", schema: "public", table: "sessions", filter: `id=eq.${id}` }, refresh);
        } else if (kind === "user") {
          ch.on("postgres_changes", { event: "*", schema: "public", table: "invitations", filter: `helper_id=eq.${id}` }, refresh);
          ch.on("postgres_changes", { event: "*", schema: "public", table: "invitations", filter: `requester_id=eq.${id}` }, refresh);
          ch.on("postgres_changes", { event: "*", schema: "public", table: "requests", filter: `requester_id=eq.${id}` }, refresh);
        }
      }
      ch.subscribe((s) => setStatus(s === "SUBSCRIBED" ? "live" : s === "CLOSED" ? "offline" : "reconnecting"));
      cleanup = () => { sb.removeChannel(ch); };
    }

    // Safety nets: refresh on focus/reconnect, and a slow poll in case a push is missed.
    const onOnline = () => { setStatus("reconnecting"); refresh(); };
    const onOffline = () => setStatus("offline");
    const onFocus = () => refresh();
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    window.addEventListener("focus", onFocus);
    const poll = setInterval(refresh, 30_000);
    return () => {
      cleanup();
      clearTimeout(timer);
      clearInterval(poll);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
      window.removeEventListener("focus", onFocus);
    };
  }, [key, cfg.mode, cfg.supabaseUrl, cfg.supabaseAnonKey, router]);

  return status;
}

export function LiveRefresher({ topics }: { topics: string[] }) {
  useLive(topics);
  return null;
}

export function LiveDot({ status }: { status: LiveStatus }) {
  const label = { connecting: "Connecting…", live: "Live", reconnecting: "Reconnecting…", offline: "Offline" }[status];
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted" role="status" aria-live="polite">
      <span aria-hidden className={cx("h-2 w-2 rounded-full", status === "live" ? "bg-teal" : status === "offline" ? "bg-rose-ink" : "animate-pulse-dot bg-amber-ink")} />
      {label}
    </span>
  );
}

export function OfflineBanner() {
  const [offline, setOffline] = useState(false);
  useEffect(() => {
    const update = () => setOffline(!navigator.onLine);
    update();
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => { window.removeEventListener("online", update); window.removeEventListener("offline", update); };
  }, []);
  if (!offline) return null;
  return (
    <div role="alert" className="sticky top-0 z-50 bg-ink px-4 py-2 text-center text-sm text-white">
      You&apos;re offline. Messages and changes won&apos;t send until you reconnect.
    </div>
  );
}
