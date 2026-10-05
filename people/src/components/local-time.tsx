"use client";
// Times render in the viewer's own timezone (the server runs in UTC).
export function LocalTime({ iso, mode = "datetime" }: { iso: string; mode?: "datetime" | "date" | "time" }) {
  const d = new Date(iso);
  const opts: Intl.DateTimeFormatOptions =
    mode === "date" ? { month: "short", day: "numeric", year: "numeric" }
    : mode === "time" ? { hour: "numeric", minute: "2-digit" }
    : { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" };
  return <time dateTime={iso} suppressHydrationWarning>{d.toLocaleString(undefined, opts)}</time>;
}
