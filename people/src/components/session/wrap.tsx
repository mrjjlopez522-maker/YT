"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { addTakeaway, requestFollowUp, wrapUp } from "@/app/actions";
import type { SessionSnapshot } from "@/lib/server/service";
import { ReportDialog } from "../report-dialog";
import { Button, Card, Chip, Input, Label, Notice, Textarea } from "../ui";

export function WrapUp({ snap, savedTakeaway }: { snap: SessionSnapshot; savedTakeaway: boolean }) {
  const router = useRouter();
  const other = snap.other.profile;
  const isRequester = snap.me.role === "requester";
  const [pending, start] = useTransition();
  const [err, setErr] = useState<string | null>(null);

  const [addressed, setAddressed] = useState(snap.me.addressed);
  const [reconnect, setReconnect] = useState(snap.me.reconnectOptIn);
  const [helpful, setHelpful] = useState<number | null>(null);
  const [respectful, setRespectful] = useState(true);
  const [comment, setComment] = useState("");
  const [sent, setSent] = useState(snap.feedbackGiven);

  const openItems = snap.checklist.filter((i) => !i.done).map((i) => `- ${i.text}`).join("\n");
  const doneItems = snap.checklist.filter((i) => i.done).map((i) => `- ${i.text} ✓`).join("\n");
  const [title, setTitle] = useState(snap.request.question.slice(0, 120));
  const [body, setBody] = useState([snap.sharedNote.body, doneItems].filter(Boolean).join("\n\n"));
  const [next, setNext] = useState(openItems);
  const [saved, setSaved] = useState(savedTakeaway);
  const [report, setReport] = useState(false);

  const submitFeedback = () => start(async () => {
    setErr(null);
    const r = await wrapUp(snap.session.id, { addressed, reconnect, ...(helpful && !sent ? { helpful, respectful, comment } : {}) });
    if (!r.ok) return setErr(r.error);
    if (helpful) setSent(true);
    router.refresh();
  });

  return (
    <div className="space-y-6">
      <Card className="p-5 sm:p-6">
        <h2 className="font-display text-xl font-semibold">{isRequester ? "Did this help with what you came for?" : "How did it go?"}</h2>
        {isRequester && (
          <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Was your question addressed?">
            {([["yes", "Yes"], ["partly", "Partly"], ["no", "Not really"]] as const).map(([v, l]) => (
              <Chip key={v} active={addressed === v} onClick={() => setAddressed(v)}>{l}</Chip>
            ))}
          </div>
        )}
        {!sent ? (
          <div className="mt-5 space-y-4 border-t border-line pt-4">
            <div>
              <p className="text-sm font-medium">How helpful was {other.displayName}? <span className="font-normal text-muted">(private)</span></p>
              <div className="mt-2 flex gap-2" role="group" aria-label="Helpfulness from 1 to 5">
                {[1, 2, 3, 4, 5].map((n) => <Chip key={n} active={helpful === n} onClick={() => setHelpful(n)} aria-label={`${n} of 5`}>{n}</Chip>)}
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" className="h-4 w-4 accent-[var(--color-teal)]" checked={respectful} onChange={(e) => setRespectful(e.target.checked)} />
              They were respectful
            </label>
            <div>
              <Label htmlFor="fb" hint="(optional, only they see it — never public)">A note for {other.displayName}</Label>
              <Textarea id="fb" rows={2} maxLength={1000} value={comment} onChange={(e) => setComment(e.target.value)} />
            </div>
          </div>
        ) : <p className="mt-3 text-sm text-teal">Feedback sent — thank you.</p>}

        <label className="mt-4 flex items-start gap-3 border-t border-line pt-4 text-sm">
          <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[var(--color-indigo)]" checked={reconnect} disabled={snap.blocked} onChange={(e) => setReconnect(e.target.checked)} />
          <span>I&apos;d be happy to talk with {other.displayName} again<span className="block text-muted">Only if you both tick this can either of you send a follow-up request. No contact details are shared.</span></span>
        </label>
        {err && <Notice tone="rose" className="mt-3">{err}</Notice>}
        <Button className="mt-4" onClick={submitFeedback} disabled={pending}>{pending ? "Saving…" : "Save"}</Button>
      </Card>

      <Card className="p-5 sm:p-6">
        <h2 className="font-display text-xl font-semibold">Keep what was useful</h2>
        <p className="mt-1 text-sm text-muted">Saved to My learning — only you can see it. Pre-filled from your shared notes and checklist; edit before saving.</p>
        {saved ? (
          <Notice tone="teal" className="mt-4">Saved. <Link className="underline" href="/learning">Open My learning</Link></Notice>
        ) : (
          <form className="mt-4 space-y-3" onSubmit={(e) => { e.preventDefault(); start(async () => { const r = await addTakeaway({ sessionId: snap.session.id, title, body, nextSteps: next }); if (r.ok) setSaved(true); else setErr(r.error); }); }}>
            <div><Label htmlFor="tt">Title</Label><Input id="tt" value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} /></div>
            <div><Label htmlFor="tb">What I learned</Label><Textarea id="tb" rows={5} value={body} onChange={(e) => setBody(e.target.value)} /></div>
            <div><Label htmlFor="tn">Next steps</Label><Textarea id="tn" rows={3} value={next} onChange={(e) => setNext(e.target.value)} /></div>
            <Button type="submit" variant="teal" disabled={pending || !title.trim()}>Save to My learning</Button>
          </form>
        )}
      </Card>

      {snap.reconnectBoth && !snap.blocked && <FollowUp sessionId={snap.session.id} name={other.displayName} />}

      <p className="text-sm text-muted">
        Something wrong? <button className="underline" onClick={() => setReport(true)}>Report {other.displayName}</button>. Only moderators see reports.
      </p>
      {report && <ReportDialog userId={snap.other.userId} name={other.displayName} sessionId={snap.session.id} onClose={() => setReport(false)} />}
    </div>
  );
}

function FollowUp({ sessionId, name }: { sessionId: string; name: string }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [timing, setTiming] = useState<"now" | "later">("later");
  const [time, setTime] = useState("");
  const [pending, start] = useTransition();
  const [err, setErr] = useState<string | null>(null);
  return (
    <Card className="p-5 sm:p-6">
      <h2 className="font-display text-xl font-semibold">You both want to reconnect</h2>
      <p className="mt-1 text-sm text-muted">Send {name} a follow-up request. They can accept or decline as usual.</p>
      <form className="mt-4 space-y-3" onSubmit={(e) => {
        e.preventDefault();
        start(async () => {
          const r = await requestFollowUp(sessionId, { question: q, timing, preferredTime: timing === "later" && time ? new Date(time).toISOString() : undefined });
          if (!r.ok) setErr(r.error); else router.push(`/requests/${r.data.requestId}`);
        });
      }}>
        <div><Label htmlFor="fq">What would you like to pick up?</Label><Textarea id="fq" rows={2} maxLength={600} value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <div className="flex flex-wrap gap-2">
          <Chip active={timing === "now"} onClick={() => setTiming("now")}>Now</Chip>
          <Chip active={timing === "later"} onClick={() => setTiming("later")}>At a set time</Chip>
        </div>
        {timing === "later" && <div className="max-w-xs"><Label htmlFor="ft">Time</Label><Input id="ft" type="datetime-local" value={time} onChange={(e) => setTime(e.target.value)} required /></div>}
        {err && <Notice tone="rose">{err}</Notice>}
        <Button type="submit" disabled={pending || q.trim().length < 5}>Send follow-up</Button>
      </form>
    </Card>
  );
}
