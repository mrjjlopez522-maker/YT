"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { respondAsync, respondInvitation, setAvailableNow } from "@/app/actions";
import { Button, Notice, Textarea, cx } from "./ui";
import { useNow } from "./use-now";

export function AvailabilityToggle({ until }: { until: string | null }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [err, setErr] = useState<string | null>(null);
  const now = useNow(15_000);
  const on = !!until && now !== null && new Date(until).getTime() > now;
  const set = (m: number) => start(async () => {
    const r = await setAvailableNow(m);
    if (!r.ok) setErr(r.error); else router.refresh();
  });
  return (
    <div className={cx("rounded-2xl border p-4", on ? "border-teal/30 bg-teal-soft" : "border-line bg-card")}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="font-semibold">{on ? "You're available now" : "You're not available right now"}</p>
          <p className="text-sm text-muted" suppressHydrationWarning>
            {on ? `Until ${new Date(until!).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}. It switches off by itself.` : "Turn this on whenever you feel like helping. There's no expectation to stay on."}
          </p>
        </div>
        {on ? (
          <Button variant="secondary" size="sm" onClick={() => set(0)} disabled={pending}>Go unavailable</Button>
        ) : (
          <div className="flex flex-wrap gap-2" role="group" aria-label="Be available for">
            {[30, 60, 120].map((m) => (
              <Button key={m} size="sm" variant="teal" onClick={() => set(m)} disabled={pending}>{m < 60 ? `${m} min` : `${m / 60} h`}</Button>
            ))}
          </div>
        )}
      </div>
      {err && <p role="alert" className="mt-2 text-sm text-rose-ink">{err}</p>}
    </div>
  );
}

export function InvitationButtons({ invitationId }: { invitationId: string }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<{ tone: "rose" | "neutral"; text: string } | null>(null);
  const respond = (accept: boolean) => start(async () => {
    setMsg(null);
    const r = await respondInvitation(invitationId, accept);
    if (!r.ok) { setMsg({ tone: "rose", text: r.error }); router.refresh(); return; }
    if (r.data.status === "accepted") router.push(`/sessions/${r.data.sessionId}`);
    else if (r.data.status === "expired") { setMsg({ tone: "neutral", text: "This invitation expired before you answered — no problem." }); router.refresh(); }
    else if (r.data.status === "unavailable") { setMsg({ tone: "neutral", text: "This request is no longer available." }); router.refresh(); }
    else router.refresh();
  });
  return (
    <div>
      <div className="flex gap-2">
        <Button variant="teal" onClick={() => respond(true)} disabled={pending}>Accept</Button>
        <Button variant="secondary" onClick={() => respond(false)} disabled={pending}>Decline</Button>
      </div>
      {msg && <Notice tone={msg.tone} className="mt-2">{msg.text}</Notice>}
    </div>
  );
}

export function AsyncAnswerForm({ requestId }: { requestId: string }) {
  const router = useRouter();
  const [body, setBody] = useState("");
  const [pending, start] = useTransition();
  const [err, setErr] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  if (sent) return <Notice tone="teal">Sent. They&apos;ll see your reply on their request.</Notice>;
  return (
    <form onSubmit={(e) => { e.preventDefault(); start(async () => { const r = await respondAsync(requestId, body); if (!r.ok) setErr(r.error); else { setSent(true); router.refresh(); } }); }}>
      <label htmlFor="ans" className="mb-1.5 block text-sm font-medium">Your reply</label>
      <Textarea id="ans" rows={6} maxLength={3000} value={body} onChange={(e) => setBody(e.target.value)} placeholder="Share what worked for you. Be clear about what's your own experience." />
      <p className="mt-1 text-xs text-muted">Shown with your display name as a personal perspective. Don&apos;t include contact details.</p>
      {err && <p role="alert" className="mt-2 text-sm text-rose-ink">{err}</p>}
      <Button type="submit" className="mt-3" disabled={pending || body.trim().length < 2}>{pending ? "Sending…" : "Send reply"}</Button>
    </form>
  );
}
