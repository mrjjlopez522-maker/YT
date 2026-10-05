"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import {
  broadenRequest, cancelInvitation, cancelRequest, inviteHelper, leaveForLater, startAutoMatch,
} from "@/app/actions";
import { Button, Input, Label, Notice } from "../ui";
import { useNow } from "../use-now";

function useAction() {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const run = (fn: () => Promise<{ ok: boolean; error?: string }>, after?: () => void) =>
    start(async () => {
      setError(null);
      const res = await fn();
      if (!res.ok) setError(res.error ?? "Something went wrong.");
      else { after?.(); router.refresh(); }
    });
  return { pending, error, run };
}

export function InviteButton({ requestId, helperId, name, disabled }: { requestId: string; helperId: string; name: string; disabled?: boolean }) {
  const { pending, error, run } = useAction();
  return (
    <div>
      <Button onClick={() => run(() => inviteHelper(requestId, helperId))} disabled={pending || disabled} className="w-full sm:w-auto">
        {pending ? "Sending…" : `Ask ${name}`}
      </Button>
      {error && <p role="alert" className="mt-2 text-sm text-rose-ink">{error}</p>}
    </div>
  );
}

export function AutoMatchButton({ requestId }: { requestId: string }) {
  const { pending, error, run } = useAction();
  return (
    <div>
      <Button variant="secondary" onClick={() => run(() => startAutoMatch(requestId))} disabled={pending}>
        {pending ? "Matching…" : "Match me automatically"}
      </Button>
      {error && <p role="alert" className="mt-2 text-sm text-rose-ink">{error}</p>}
    </div>
  );
}

export function Countdown({ until, onDone }: { until: string; onDone?: () => void }) {
  const now = useNow(1000);
  const router = useRouter();
  const left = now === null ? null : Math.max(0, new Date(until).getTime() - now);
  useEffect(() => {
    if (left === 0) { onDone?.(); const t = setTimeout(() => router.refresh(), 800); return () => clearTimeout(t); }
  }, [left === 0]); // eslint-disable-line react-hooks/exhaustive-deps
  if (left === null) return <span>…</span>;
  const s = Math.floor(left / 1000);
  if (s > 3600) return <span>{Math.round(s / 3600)} h</span>;
  return <span className="tabular-nums">{Math.floor(s / 60)}:{String(s % 60).padStart(2, "0")}</span>;
}

export function WithdrawButton({ invitationId }: { invitationId: string }) {
  const { pending, error, run } = useAction();
  return (
    <>
      <Button variant="ghost" size="sm" onClick={() => run(() => cancelInvitation(invitationId))} disabled={pending}>Withdraw</Button>
      {error && <p role="alert" className="text-sm text-rose-ink">{error}</p>}
    </>
  );
}

export function NoMatchOptions({ requestId, broaden, canLeave }: {
  requestId: string; broaden: { key: "formats" | "topic" | "timing"; label: string }[]; canLeave: boolean;
}) {
  const { pending, error, run } = useAction();
  const [time, setTime] = useState("");
  const [showTime, setShowTime] = useState(false);
  return (
    <div className="space-y-4">
      {canLeave && (
        <div className="rounded-2xl border border-line bg-card p-4">
          <p className="font-medium">Leave it for a written reply</p>
          <p className="mt-0.5 text-sm text-muted">People with matching topics can answer when they&apos;re free. You&apos;ll see replies here.</p>
          <Button variant="secondary" size="sm" className="mt-3" disabled={pending} onClick={() => run(() => leaveForLater(requestId))}>Leave my question</Button>
        </div>
      )}
      <div className="rounded-2xl border border-line bg-card p-4">
        <p className="font-medium">Propose a time instead</p>
        <p className="mt-0.5 text-sm text-muted">We&apos;ll look for people who are usually free then.</p>
        {showTime ? (
          <form className="mt-3 flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (time) run(() => broadenRequest(requestId, "timing", new Date(time).toISOString())); }}>
            <div>
              <Label htmlFor="pt">Time (your local time)</Label>
              <Input id="pt" type="datetime-local" value={time} onChange={(e) => setTime(e.target.value)} required />
            </div>
            <Button type="submit" size="sm" disabled={pending || !time}>Search at that time</Button>
          </form>
        ) : (
          <Button variant="secondary" size="sm" className="mt-3" onClick={() => setShowTime(true)}>Pick a time</Button>
        )}
      </div>
      {broaden.filter((b) => b.key !== "timing").map((b) => (
        <div key={b.key} className="rounded-2xl border border-line bg-card p-4">
          <p className="font-medium">Widen the search?</p>
          <p className="mt-0.5 text-sm text-muted">Only if you&apos;re happy to: {b.label.toLowerCase()}.</p>
          <Button variant="secondary" size="sm" className="mt-3" disabled={pending} onClick={() => run(() => broadenRequest(requestId, b.key))}>{b.label}</Button>
        </div>
      ))}
      {error && <Notice tone="rose">{error}</Notice>}
    </div>
  );
}

export function CancelRequestButton({ requestId }: { requestId: string }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [confirm, setConfirm] = useState(false);
  if (!confirm) return <Button variant="ghost" size="sm" onClick={() => setConfirm(true)}>Cancel request</Button>;
  return (
    <span className="inline-flex items-center gap-2 text-sm">
      Cancel this request?
      <Button variant="danger" size="sm" disabled={pending} onClick={() => start(async () => { await cancelRequest(requestId); router.push("/requests"); })}>Yes, cancel</Button>
      <Button variant="ghost" size="sm" onClick={() => setConfirm(false)}>Keep it</Button>
    </span>
  );
}
