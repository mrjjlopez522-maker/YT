"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { ArrowRight, Compass, Dumbbell, GraduationCap, HelpCircle, Shuffle } from "lucide-react";
import { surpriseMe } from "@/app/actions";
import { EXAMPLE_PROMPTS, INTENTS } from "@/lib/domain/prompts";
import type { Intent } from "@/lib/domain/types";
import { Button, Notice, cx } from "../ui";

const ICONS: Record<Intent, typeof HelpCircle> = { ask: HelpCircle, learn: GraduationCap, move: Dumbbell, explore: Compass };

export function Composer({ firstName }: { firstName: string }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [intent, setIntent] = useState<Intent | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [pending, start] = useTransition();

  const go = (extra: Record<string, string> = {}) => {
    const p = new URLSearchParams({ ...(q.trim() ? { q: q.trim() } : {}), ...(intent ? { intent } : {}), ...extra });
    router.push(`/requests/new?${p}`);
  };

  const surprise = () =>
    start(async () => {
      setNote(null);
      const res = await surpriseMe();
      if (!res.ok) return setNote(res.error);
      if (res.data.kind === "no_interests") return setNote("Add a few interests to your profile first — Surprise me only picks from things you said you're curious about.");
      const none = res.data.kind === "none_available" ? "&none=1" : "";
      router.push(`/requests/new?intent=explore&topic=${encodeURIComponent(res.data.topicId)}&surprise=1${none}`);
    });

  return (
    <div className="animate-rise">
      <p className="text-sm font-medium text-teal">Hi {firstName}</p>
      <h1 className="mt-1 font-display text-[34px] font-semibold leading-[1.1] tracking-tight sm:text-5xl">
        What do you need right now?
      </h1>

      <form
        className="mt-6"
        onSubmit={(e) => { e.preventDefault(); if (q.trim().length >= 5) go(); }}
      >
        <label htmlFor="q" className="sr-only">What are you trying to figure out?</label>
        <div className="rounded-[1.5rem] border border-line-2 bg-card p-2 shadow-[var(--shadow-soft)] focus-within:border-indigo">
          <textarea
            id="q"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && q.trim().length >= 5) { e.preventDefault(); go(); } }}
            rows={3}
            maxLength={600}
            placeholder="What are you trying to figure out?"
            className="block w-full resize-none rounded-2xl bg-transparent px-3 py-2.5 text-lg leading-relaxed placeholder:text-muted/70 focus:outline-none focus-visible:outline-none"
          />
          <div className="flex items-center justify-between gap-2 px-2 pb-1">
            <span className="text-xs text-muted">{intent ? `Intent: ${INTENTS.find((i) => i.id === intent)?.label}` : "Shift+Enter for a new line"}</span>
            <Button type="submit" disabled={q.trim().length < 5}>
              Find someone <ArrowRight size={16} aria-hidden />
            </Button>
          </div>
        </div>
      </form>

      <div className="mt-4">
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">Try one</p>
        <ul className="flex gap-2 overflow-x-auto pb-1 [scrollbar-width:none] sm:flex-wrap">
          {EXAMPLE_PROMPTS.map((p) => (
            <li key={p} className="shrink-0">
              <button
                type="button"
                onClick={() => { setQ(p); document.getElementById("q")?.focus(); }}
                className="max-w-[18rem] truncate rounded-full border border-line bg-paper-2/60 px-3.5 py-1.5 text-left text-sm text-ink-2 hover:border-line-2 hover:bg-card sm:max-w-none"
              >
                {p}
              </button>
            </li>
          ))}
        </ul>
      </div>

      <fieldset className="mt-8">
        <legend className="mb-3 text-xs font-medium uppercase tracking-wide text-muted">What kind of help?</legend>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {INTENTS.map((it) => {
            const Icon = ICONS[it.id];
            const on = intent === it.id;
            return (
              <button
                key={it.id}
                type="button"
                aria-pressed={on}
                onClick={() => setIntent(on ? null : it.id)}
                className={cx(
                  "group rounded-2xl border p-4 text-left transition-all",
                  on ? "border-indigo bg-indigo-soft" : "border-line bg-card hover:-translate-y-0.5 hover:border-line-2 hover:shadow-[var(--shadow-soft)]",
                )}
              >
                <Icon size={20} aria-hidden className={on ? "text-indigo" : "text-teal"} />
                <p className="mt-3 font-semibold">{it.label}</p>
                <p className="mt-0.5 text-sm leading-snug text-muted">{it.blurb}</p>
              </button>
            );
          })}
        </div>
      </fieldset>

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <Button variant="secondary" onClick={surprise} disabled={pending}>
          <Shuffle size={16} aria-hidden /> {pending ? "Looking…" : "Surprise me"}
        </Button>
        <span className="text-sm text-muted">Picks an Explore topic from your own interests.</span>
      </div>
      {note && <Notice tone="amber" className="mt-3">{note}</Notice>}
    </div>
  );
}
