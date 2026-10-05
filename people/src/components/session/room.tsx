"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useTransition } from "react";
import { Check, Flag, MoreHorizontal, Pencil, Send, ShieldOff, Timer, Trash2, X } from "lucide-react";
import {
  addChecklistItem, blockPerson, endSession, removeChecklistItem, savePrivateNote, saveSharedNote, sendMessage,
  setGoal, setSessionFlag, setTimer, startSession, toggleChecklistItem,
} from "@/app/actions";
import { explorePrompts, intentLabel, RESPECT_NOTE } from "@/lib/domain/prompts";
import { isPerspective, topicPath } from "@/lib/domain/topics";
import type { SessionSnapshot } from "@/lib/server/service";
import { usePublicConfig } from "../config-context";
import { LiveDot, useLive } from "../live";
import { ReportDialog } from "../report-dialog";
import { Avatar, Badge, Button, Card, Input, Notice, Textarea, cx } from "../ui";
import { CallPanel } from "./call-panel";
import { useNow } from "../use-now";

type Snap = SessionSnapshot;

export function SessionRoom({ snap }: { snap: Snap }) {
  const router = useRouter();
  const cfg = usePublicConfig();
  const status = useLive([`session:${snap.session.id}`]);
  const [tab, setTab] = useState<"chat" | "plan" | "notes">("chat");
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const s = snap.session;
  const live = s.status === "active" || s.status === "scheduled";
  const writable = live && !snap.blocked;
  const other = snap.other.profile;

  const act = (fn: () => Promise<{ ok: boolean; error?: string }>) =>
    start(async () => {
      setError(null);
      const r = await fn();
      if (!r.ok) setError(r.error ?? "Something went wrong.");
      router.refresh();
    });

  useEffect(() => {
    if (s.status === "ended") {
      const t = setTimeout(() => router.push(`/sessions/${s.id}/wrap`), 1500);
      return () => clearTimeout(t);
    }
  }, [s.status, s.id, router]);

  const intentPanel = <IntentPanel snap={snap} act={act} writable={writable} />;
  const plan = (
    <div className="space-y-4">
      {intentPanel}
      <Checklist snap={snap} act={act} writable={writable} />
      <TimerCard snap={snap} act={act} writable={s.status === "active" && !snap.blocked} />
    </div>
  );
  const notes = <Notes snap={snap} writable={!snap.blocked} />;

  return (
    <div className="mx-auto max-w-6xl">
      {/* Header */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Link href="/sessions" className="text-sm text-muted hover:text-ink">← Sessions</Link>
        <span className="ml-auto"><LiveDot status={status} /></span>
      </div>

      <Card className="p-5 sm:p-6">
        <div className="flex items-center gap-3">
          <Avatar name={other.displayName} color={other.avatarColor} size={44} />
          <p className="min-w-0 flex-1 text-sm text-muted">
            {snap.me.role === "requester" ? "Helping you" : "You're helping"}
            <Link href={`/people/${other.id}`} className="block truncate text-base font-semibold text-ink hover:underline">{other.displayName}</Link>
          </p>
          <SafetyMenu snap={snap} act={act} />
        </div>
        <h1 className="mt-4 font-display text-xl font-semibold leading-snug sm:text-2xl">{snap.request.question}</h1>
        <div className="mt-2 flex flex-wrap gap-2">
          <Badge tone="indigo">{intentLabel(snap.request.intent)}</Badge>
          <Badge>{topicPath(snap.request.topicId)}</Badge>
          <Badge className="capitalize">{s.format}</Badge>
          {s.status === "scheduled" && <Badge tone="amber">Upcoming</Badge>}
          {s.status === "ended" && <Badge>Ended</Badge>}
        </div>
        <Goal snap={snap} act={act} writable={writable} />
        {snap.keepGoingBoth && s.status === "active" && (
          <p className="mt-3 rounded-xl bg-teal-soft px-3 py-2 text-sm text-teal">You both chose to keep going. Take the time you need.</p>
        )}
      </Card>

      {isPerspective(snap.request.topicId) && <Notice tone="indigo" className="mt-4">{RESPECT_NOTE}</Notice>}
      {snap.blocked && <Notice tone="rose" className="mt-4">This conversation is closed. Neither of you can send messages or join a call.</Notice>}
      {s.status === "ended" && <Notice className="mt-4" title="This session has ended.">Taking you to the wrap-up… <Link className="underline" href={`/sessions/${s.id}/wrap`}>Go now</Link></Notice>}
      {s.status === "cancelled" && <Notice className="mt-4">This session was cancelled.</Notice>}
      {s.status === "scheduled" && <ScheduledBar snap={snap} act={act} pending={pending} />}
      {error && <Notice tone="rose" className="mt-4">{error}</Notice>}

      {/* Mobile tabs */}
      <div role="tablist" aria-label="Session" className="mt-5 flex rounded-xl bg-paper-2 p-1 lg:hidden">
        {(["chat", "plan", "notes"] as const).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={cx("flex-1 rounded-lg px-3 py-2 text-sm font-medium capitalize", tab === t ? "bg-card shadow-sm" : "text-muted")}>
            {t === "plan" ? "Together" : t}
          </button>
        ))}
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className={cx(tab !== "chat" && "hidden lg:block")}>
          {s.format !== "text" && s.status === "active" && !snap.blocked && (
            <Card className="mb-5 p-4">
              <CallPanel
                sessionId={s.id}
                format={s.format}
                configured={cfg.livekit}
                videoAllowed={snap.videoAllowed}
                myVideoOptIn={snap.me.videoOptIn}
                otherVideoOptIn={snap.other.videoOptIn}
                otherName={other.displayName}
                onToggleVideoOptIn={(v) => act(() => setSessionFlag(s.id, "videoOptIn", v))}
              />
            </Card>
          )}
          <Chat snap={snap} writable={writable} />
        </div>
        <aside className="space-y-5">
          <div className={cx(tab !== "plan" && "hidden lg:block")}>{plan}</div>
          <div className={cx(tab !== "notes" && "hidden lg:block")}>{notes}</div>
        </aside>
      </div>
    </div>
  );
}

type Act = (fn: () => Promise<{ ok: boolean; error?: string }>) => void;

function Goal({ snap, act, writable }: { snap: Snap; act: Act; writable: boolean }) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(snap.session.goal);
  const label = snap.request.intent === "move" ? "One achievable goal" : "What would make this useful";
  return (
    <div className="mt-4 rounded-2xl bg-paper-2/70 p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</p>
      {editing ? (
        <form className="mt-2 flex gap-2" onSubmit={(e) => { e.preventDefault(); act(() => setGoal(snap.session.id, val)); setEditing(false); }}>
          <label htmlFor="goal" className="sr-only">{label}</label>
          <Input id="goal" value={val} onChange={(e) => setVal(e.target.value)} maxLength={300} autoFocus />
          <Button type="submit" size="md">Save</Button>
        </form>
      ) : (
        <div className="mt-1 flex items-start gap-2">
          <p className="flex-1 text-[15px]">{snap.session.goal}</p>
          {writable && (
            <button onClick={() => { setVal(snap.session.goal); setEditing(true); }} className="rounded-lg p-1 text-muted hover:text-ink" aria-label="Edit goal">
              <Pencil size={16} aria-hidden />
            </button>
          )}
        </div>
      )}
      <p className="mt-2 text-xs text-muted">Agree on this together — either of you can edit it.</p>
    </div>
  );
}

function ScheduledBar({ snap, act, pending }: { snap: Snap; act: Act; pending: boolean }) {
  const at = snap.session.scheduledAt ? new Date(snap.session.scheduledAt) : null;
  const now = useNow(15_000);
  const canStart = at && now !== null && at.getTime() - now <= 10 * 60_000;
  return (
    <Card className="mt-4 flex flex-wrap items-center gap-3 p-4">
      <p className="flex-1 text-sm" suppressHydrationWarning>
        Booked for <strong>{at?.toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit", month: "short", day: "numeric" })}</strong>. You can chat here before it starts.
      </p>
      <Button variant="teal" disabled={!canStart || pending} onClick={() => act(() => startSession(snap.session.id))}>
        {canStart ? "Start session" : "Opens 10 min before"}
      </Button>
    </Card>
  );
}

function Chat({ snap, writable }: { snap: Snap; writable: boolean }) {
  const router = useRouter();
  const [body, setBody] = useState("");
  const [sending, setSending] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [optimistic, setOptimistic] = useState<{ id: string; body: string; at: string }[]>([]);
  const list = useRef<HTMLOListElement>(null);
  const names: Record<string, string> = { [snap.me.userId]: "You", [snap.other.userId]: snap.other.profile.displayName };

  // Hide optimistic bubbles once the server copy arrives.
  const pendingMine = optimistic.filter((m) => !snap.messages.some((x) => x.senderId === snap.me.userId && x.body === m.body && x.createdAt >= m.at));
  useEffect(() => {
    list.current?.lastElementChild?.scrollIntoView({ block: "nearest" });
  }, [snap.messages.length, pendingMine.length]);

  const send = async () => {
    const text = body.trim();
    if (!text) return;
    setSending(true);
    setErr(null);
    const temp = { id: `tmp-${Date.now()}`, body: text, at: new Date(Date.now() - 60_000).toISOString() };
    setOptimistic((o) => [...o, temp]);
    setBody("");
    const r = await sendMessage(snap.session.id, text);
    setSending(false);
    if (!r.ok) {
      setErr(r.error);
      setOptimistic((o) => o.filter((m) => m.id !== temp.id));
      setBody(text);
    }
    router.refresh();
  };

  return (
    <Card className="flex h-[min(60vh,560px)] flex-col">
      <ol ref={list} className="flex-1 space-y-3 overflow-y-auto p-4" aria-live="polite" aria-label="Messages">
        {snap.messages.length === 0 && <li className="text-center text-sm text-muted">No messages yet.</li>}
        {snap.messages.map((m) =>
          m.senderId === null ? (
            <li key={m.id} className="text-center text-xs text-muted">{m.body}</li>
          ) : (
            <li key={m.id} className={cx("flex", m.senderId === snap.me.userId ? "justify-end" : "justify-start")}>
              <div className={cx("max-w-[85%] rounded-2xl px-3.5 py-2", m.senderId === snap.me.userId ? "rounded-br-md bg-indigo text-white" : "rounded-bl-md bg-paper-2")}>
                <p className="sr-only">{names[m.senderId] ?? "Someone"}:</p>
                <p className="prewrap text-[15px] leading-relaxed">{m.body}</p>
                <p className={cx("mt-0.5 text-[11px]", m.senderId === snap.me.userId ? "text-white/70" : "text-muted")} suppressHydrationWarning>
                  {new Date(m.createdAt).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}
                </p>
              </div>
            </li>
          ),
        )}
        {pendingMine.map((m) => (
          <li key={m.id} className="flex justify-end">
            <div className="max-w-[85%] rounded-2xl rounded-br-md bg-indigo/70 px-3.5 py-2 text-white">
              <p className="prewrap text-[15px]">{m.body}</p>
              <p className="mt-0.5 text-[11px] text-white/70">Sending…</p>
            </div>
          </li>
        ))}
      </ol>
      {writable ? (
        <form className="flex items-end gap-2 border-t border-line p-3" onSubmit={(e) => { e.preventDefault(); send(); }}>
          <label htmlFor="msg" className="sr-only">Message</label>
          <Textarea
            id="msg" rows={1} maxLength={2000} value={body} onChange={(e) => setBody(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
            placeholder="Write a message" className="max-h-32 min-h-11 resize-none"
          />
          <Button type="submit" aria-label="Send" disabled={sending || !body.trim()} className="h-11 w-11 shrink-0 px-0"><Send size={18} aria-hidden /></Button>
        </form>
      ) : (
        <p className="border-t border-line p-3 text-center text-sm text-muted">Messaging is closed for this session.</p>
      )}
      {err && <p role="alert" className="px-4 pb-3 text-sm text-rose-ink">{err}</p>}
    </Card>
  );
}

function IntentPanel({ snap, act, writable }: { snap: Snap; act: Act; writable: boolean }) {
  const r = snap.request;
  if (r.intent === "explore") {
    return (
      <Card className="p-4">
        <p className="font-semibold">Conversation prompts</p>
        <p className="mb-3 text-sm text-muted">Optional. Tap one to send it.</p>
        <ul className="space-y-2">
          {explorePrompts(r.topicId).map((p) => (
            <li key={p}>
              <button disabled={!writable} onClick={() => act(() => sendMessage(snap.session.id, p))}
                className="w-full rounded-xl border border-line bg-paper/60 px-3 py-2 text-left text-sm hover:border-line-2 disabled:opacity-50">{p}</button>
            </li>
          ))}
        </ul>
      </Card>
    );
  }
  if (r.intent === "ask") {
    return (
      <Card className="p-4">
        <p className="font-semibold">Ask → clarify → resolve</p>
        {r.clarificationAnswer ? (
          <p className="mt-2 text-sm"><span className="text-muted">{r.clarificationQuestion}</span> {r.clarificationAnswer}</p>
        ) : r.context ? <p className="prewrap mt-2 text-sm text-ink-2">{r.context}</p> : null}
        <p className="mt-2 text-sm text-muted">Write the answer you land on in shared notes, so it&apos;s saved for later.</p>
      </Card>
    );
  }
  if (r.intent === "move") {
    return (
      <Card className="p-4">
        <p className="font-semibold">Get moving</p>
        <ol className="mt-2 space-y-1 text-sm text-ink-2">
          <li>1. Agree on one small, achievable goal above.</li>
          <li>2. Start a focus timer below and work.</li>
          <li>3. Check in when it ends — tick it off or adjust.</li>
        </ol>
      </Card>
    );
  }
  return (
    <Card className="p-4">
      <p className="font-semibold">Learn in small steps</p>
      <p className="mt-1 text-sm text-muted">Add steps as they&apos;re shown, then a &ldquo;Let me try&rdquo; item to practise.</p>
    </Card>
  );
}

function Checklist({ snap, act, writable }: { snap: Snap; act: Act; writable: boolean }) {
  const learn = snap.request.intent === "learn";
  const [text, setText] = useState("");
  const [kind, setKind] = useState<"step" | "try" | "task">(learn ? "step" : "task");
  const groups = learn
    ? [{ k: "step", title: "Steps" }, { k: "try", title: "Let me try" }, { k: "task", title: "Next steps" }]
    : [{ k: "task", title: "Shared checklist" }, { k: "step", title: "Steps" }, { k: "try", title: "Let me try" }];
  const items = (k: string) => snap.checklist.filter((i) => i.kind === k);
  return (
    <Card className="p-4">
      {groups.filter((g, i) => i === 0 || items(g.k).length > 0).map((g) => (
        <div key={g.k} className="mb-3">
          <p className="mb-2 font-semibold">{g.title}</p>
          {items(g.k).length === 0 && <p className="text-sm text-muted">Nothing yet.</p>}
          <ul className="space-y-1">
            {items(g.k).map((i) => (
              <li key={i.id} className="group flex items-center gap-2">
                <input
                  type="checkbox" id={`ci-${i.id}`} checked={i.done} disabled={!writable}
                  onChange={(e) => act(() => toggleChecklistItem(snap.session.id, i.id, e.target.checked))}
                  className="h-4 w-4 accent-[var(--color-teal)]"
                />
                <label htmlFor={`ci-${i.id}`} className={cx("flex-1 text-sm", i.done && "text-muted line-through")}>{i.text}</label>
                {writable && (
                  <button onClick={() => act(() => removeChecklistItem(snap.session.id, i.id))} className="rounded p-1 text-muted opacity-60 hover:opacity-100" aria-label={`Remove ${i.text}`}>
                    <Trash2 size={14} aria-hidden />
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
      {writable && (
        <form className="mt-2 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim()) { act(() => addChecklistItem(snap.session.id, text, kind)); setText(""); } }}>
          <label htmlFor="ci-new" className="sr-only">New item</label>
          <Input id="ci-new" value={text} onChange={(e) => setText(e.target.value)} maxLength={200} placeholder={kind === "try" ? "Something to try…" : "Add an item…"} className="h-10" />
          {learn && (
            <select aria-label="Item type" value={kind} onChange={(e) => setKind(e.target.value as typeof kind)} className="h-10 rounded-xl border border-line-2 bg-card px-2 text-sm">
              <option value="step">Step</option><option value="try">Try</option><option value="task">Next</option>
            </select>
          )}
          <Button type="submit" size="sm" className="h-10" aria-label="Add item"><Check size={16} aria-hidden /></Button>
        </form>
      )}
    </Card>
  );
}

function TimerCard({ snap, act, writable }: { snap: Snap; act: Act; writable: boolean }) {
  const ends = snap.session.timerEndsAt ? new Date(snap.session.timerEndsAt).getTime() : null;
  const now = useNow(1000);
  const left = ends && now !== null ? Math.max(0, ends - now) : null;
  const move = snap.request.intent === "move";
  const presets = move ? [10, 25, 45] : [5, 10, 20];
  return (
    <Card className="p-4">
      <p className="flex items-center gap-2 font-semibold"><Timer size={16} aria-hidden /> {move ? "Focus timer" : "Timer"}</p>
      {left !== null ? (
        <div className="mt-2">
          <p className="font-display text-4xl tabular-nums" aria-live="off">{Math.floor(left / 60000)}:{String(Math.floor((left % 60000) / 1000)).padStart(2, "0")}</p>
          {snap.session.timerLabel && <p className="text-sm text-muted">{snap.session.timerLabel}</p>}
          {left === 0 && <p className="mt-1 text-sm font-medium text-teal" role="status">Time&apos;s up — check in: how did it go?</p>}
          {writable && <Button variant="ghost" size="sm" className="mt-2" onClick={() => act(() => setTimer(snap.session.id, 0, ""))}><X size={14} aria-hidden /> Clear</Button>}
        </div>
      ) : (
        <p className="mt-1 text-sm text-muted">{move ? "Work alongside each other, then check in." : "Optional: keep an intro or exercise short."}</p>
      )}
      {writable && left === null && (
        <div className="mt-3 flex flex-wrap gap-2">
          {presets.map((m) => <Button key={m} variant="secondary" size="sm" onClick={() => act(() => setTimer(snap.session.id, m, move ? "Focus" : ""))}>{m} min</Button>)}
        </div>
      )}
      {snap.session.status === "active" && !snap.blocked && (
        <label className="mt-4 flex items-start gap-2 border-t border-line pt-3 text-sm">
          <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[var(--color-teal)]" checked={snap.me.keepGoing}
            onChange={(e) => act(() => setSessionFlag(snap.session.id, "keepGoing", e.target.checked))} />
          <span>
            Keep going
            <span className="block text-muted">{snap.keepGoingBoth ? "You both want to continue." : snap.other.keepGoing ? `${snap.other.profile.displayName} would like to keep going.` : "Only extends if you both choose it."}</span>
          </span>
        </label>
      )}
    </Card>
  );
}

function Notes({ snap, writable }: { snap: Snap; writable: boolean }) {
  return (
    <div className="space-y-5">
      <NoteBox
        id="shared" title="Shared notes" hint={`Visible to you and ${snap.other.profile.displayName}.`}
        initial={snap.sharedNote.body} remoteVersion={snap.sharedNote.updatedAt}
        save={(b) => saveSharedNote(snap.session.id, b)} writable={writable}
        footer={snap.sharedNote.updatedBy ? `Last edited by ${snap.sharedNote.updatedBy === snap.me.userId ? "you" : snap.other.profile.displayName}` : undefined}
      />
      <NoteBox
        id="private" title="Private notes" hint="Only you can see these." tone="private"
        initial={snap.privateNote} remoteVersion="" save={(b) => savePrivateNote(snap.session.id, b)} writable
      />
    </div>
  );
}

function NoteBox({ id, title, hint, initial, remoteVersion, save, writable, footer, tone }: {
  id: string; title: string; hint: string; initial: string; remoteVersion: string; save: (b: string) => Promise<{ ok: boolean; error?: string }>;
  writable: boolean; footer?: string; tone?: "private";
}) {
  const [val, setVal] = useState(initial);
  const [state, setState] = useState<"saved" | "dirty" | "saving" | "error">("saved");
  const focused = useRef(false);
  // Take remote updates unless the person is mid-edit.
  useEffect(() => { if (!focused.current && state !== "dirty") setVal(initial); }, [initial, remoteVersion]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (state !== "dirty") return;
    const t = setTimeout(async () => {
      setState("saving");
      const r = await save(val);
      setState(r.ok ? "saved" : "error");
    }, 800);
    return () => clearTimeout(t);
  }, [val, state]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Card className={cx("p-4", tone === "private" && "border-dashed bg-paper-2/40")}>
      <label htmlFor={`note-${id}`} className="font-semibold">{title}</label>
      <p className="mb-2 text-xs text-muted">{hint}</p>
      <Textarea
        id={`note-${id}`} rows={6} maxLength={8000} value={val} readOnly={!writable}
        onFocus={() => (focused.current = true)} onBlur={() => (focused.current = false)}
        onChange={(e) => { setVal(e.target.value); setState("dirty"); }}
      />
      <p className="mt-1 text-xs text-muted" role="status">
        {state === "saving" ? "Saving…" : state === "dirty" ? "Unsaved changes" : state === "error" ? <span className="text-rose-ink">Couldn&apos;t save — check your connection.</span> : footer ?? "Saved"}
      </p>
    </Card>
  );
}

function SafetyMenu({ snap, act }: { snap: Snap; act: Act }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState<null | "end" | "block">(null);
  const [report, setReport] = useState(false);
  const name = snap.other.profile.displayName;
  const live = snap.session.status === "active" || snap.session.status === "scheduled";
  return (
    <div className="relative">
      <div className="flex gap-2">
        {live && !snap.blocked && <Button variant="secondary" size="sm" onClick={() => setConfirm("end")}>End session</Button>}
        <Button variant="ghost" size="sm" aria-label="Safety options" aria-expanded={open} onClick={() => setOpen(!open)}><MoreHorizontal size={18} aria-hidden /></Button>
      </div>
      {open && (
        <div className="absolute right-0 z-30 mt-2 w-60 rounded-2xl border border-line bg-card p-1.5 shadow-lg" role="menu">
          <button role="menuitem" onClick={() => { setOpen(false); setReport(true); }} className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm hover:bg-paper-2"><Flag size={16} aria-hidden /> Report {name}</button>
          {!snap.iBlocked && (
            <button role="menuitem" onClick={() => { setOpen(false); setConfirm("block"); }} className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm text-rose-ink hover:bg-rose-soft"><ShieldOff size={16} aria-hidden /> Block {name}</button>
          )}
        </div>
      )}
      {confirm && (
        <div className="absolute right-0 z-30 mt-2 w-72 rounded-2xl border border-line bg-card p-4 shadow-lg" role="dialog" aria-label="Confirm">
          <p className="text-sm">
            {confirm === "end" ? "End this session for both of you? You'll go to the wrap-up." : `Block ${name}? The session ends now, and you won't be matched again. They aren't told why.`}
          </p>
          <div className="mt-3 flex gap-2">
            <Button size="sm" variant={confirm === "block" ? "danger" : "primary"} onClick={() => {
              const c = confirm; setConfirm(null);
              act(async () => {
                const r = c === "end" ? await endSession(snap.session.id) : await blockPerson(snap.other.userId);
                if (r.ok) router.push(`/sessions/${snap.session.id}/wrap`);
                return r;
              });
            }}>{confirm === "end" ? "End session" : "Block"}</Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirm(null)}>Cancel</Button>
          </div>
        </div>
      )}
      {report && <ReportDialog userId={snap.other.userId} name={name} sessionId={snap.session.id} onClose={() => setReport(false)} />}
    </div>
  );
}
