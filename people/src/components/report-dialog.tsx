"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { reportPerson } from "@/app/actions";
import { Button, Label, Notice, Select, Textarea } from "./ui";

const REASONS = [
  ["harassment", "Harassment or disrespect"],
  ["inappropriate_media", "Inappropriate video, audio or images"],
  ["unsafe_advice", "Unsafe or pressuring advice"],
  ["impersonation", "Pretending to be someone or to have credentials"],
  ["spam", "Spam or selling"],
  ["other", "Something else"],
] as const;

export function ReportDialog({ userId, name, sessionId, onClose }: { userId: string; name: string; sessionId?: string; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [reason, setReason] = useState<(typeof REASONS)[number][0]>("harassment");
  const [details, setDetails] = useState("");
  const [pending, start] = useTransition();
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  return (
    <dialog ref={ref} onClose={onClose} className="m-auto w-[min(92vw,460px)] rounded-3xl border border-line bg-card p-0 text-ink shadow-xl backdrop:bg-ink/40">
      <div className="p-6">
        <h2 className="font-display text-xl font-semibold">Report {name}</h2>
        {done ? (
          <>
            <Notice tone="teal" className="mt-4">Thanks — a moderator will review this. {name} isn&apos;t told who reported them. You can also block them to end contact right away.</Notice>
            <div className="mt-4 flex justify-end"><Button onClick={() => ref.current?.close()}>Close</Button></div>
          </>
        ) : (
          <form className="mt-4 space-y-4" onSubmit={(e) => {
            e.preventDefault();
            start(async () => {
              const r = await reportPerson({ userId, sessionId: sessionId ?? null, reason, details });
              if (r.ok) setDone(true); else setErr(r.error);
            });
          }}>
            <div>
              <Label htmlFor="rr">What happened?</Label>
              <Select id="rr" value={reason} onChange={(e) => setReason(e.target.value as typeof reason)}>
                {REASONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </Select>
            </div>
            <div>
              <Label htmlFor="rd" hint="(optional)">Details</Label>
              <Textarea id="rd" rows={4} maxLength={2000} value={details} onChange={(e) => setDetails(e.target.value)} />
              <p className="mt-1 text-xs text-muted">
                {sessionId ? "Moderators may read this session's messages to review the report. Calls aren't recorded, so describe anything that happened on audio or video." : "Reports are only visible to moderators."}
              </p>
            </div>
            <p className="text-xs text-muted">If anyone is in immediate danger, contact local emergency services.</p>
            {err && <Notice tone="rose">{err}</Notice>}
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => ref.current?.close()}>Cancel</Button>
              <Button type="submit" disabled={pending}>{pending ? "Sending…" : "Send report"}</Button>
            </div>
          </form>
        )}
      </div>
    </dialog>
  );
}
