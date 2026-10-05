"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { saveAvailability, saveHelperTopics, saveProfile, submitCredential } from "@/app/actions";
import { LANGUAGES } from "@/lib/domain/languages";
import { TOPICS, getTopic, topicPath } from "@/lib/domain/topics";
import type { AvailabilityWindow, Format, HelperTopic, Profile } from "@/lib/domain/types";
import { TopicPicker } from "./topic-picker";
import { Button, Chip, Input, Label, Notice, Select, Textarea } from "./ui";

const INTEREST_OPTIONS = TOPICS.filter((t) => t.sensitivity !== "high_stakes" && t.id.split(".").length === 2);

export function ProfileForm({ profile, onboarding }: { profile: Partial<Profile> | null; onboarding?: boolean }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState(false);
  const [f, setF] = useState(() => ({
    displayName: profile?.displayName ?? "",
    intro: profile?.intro ?? "",
    canHelpWith: profile?.canHelpWith ?? "",
    curiousAbout: profile?.curiousAbout ?? "",
    languages: profile?.languages ?? ["en"],
    formats: profile?.formats ?? (["text", "voice"] as Format[]),
    timezone: profile?.timezone ?? (typeof Intl !== "undefined" ? Intl.DateTimeFormat().resolvedOptions().timeZone : "UTC") ?? "UTC",
    locationBroad: profile?.locationBroad ?? "",
    interests: profile?.interests ?? [],
    cannotAdvise: profile?.cannotAdvise ?? "",
    sessionLengthMinutes: profile?.sessionLengthMinutes ?? 30,
    adultConfirmed: profile?.adultConfirmed ?? false,
  }));
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => { setF((x) => ({ ...x, [k]: v })); setOk(false); };
  const toggle = <T,>(arr: T[], v: T) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);

  return (
    <form className="space-y-6" onSubmit={(e) => {
      e.preventDefault();
      start(async () => {
        setErr(null);
        const r = await saveProfile(f);
        if (!r.ok) return setErr(r.error);
        if (onboarding) router.push("/?welcome=1"); else { setOk(true); router.refresh(); }
      });
    }}>
      <div className="grid gap-4 sm:grid-cols-2">
        <div><Label htmlFor="dn">Display name</Label><Input id="dn" required maxLength={40} value={f.displayName} onChange={(e) => set("displayName", e.target.value)} placeholder="First name or nickname" /></div>
        <div><Label htmlFor="loc" hint="(optional, broad)">Where you are</Label><Input id="loc" maxLength={60} value={f.locationBroad} onChange={(e) => set("locationBroad", e.target.value)} placeholder="e.g. Jordan, US West Coast" /></div>
      </div>
      <div><Label htmlFor="intro">A short introduction</Label><Textarea id="intro" rows={2} maxLength={400} value={f.intro} onChange={(e) => set("intro", e.target.value)} /></div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div><Label htmlFor="chw">I can help with…</Label><Textarea id="chw" rows={2} maxLength={400} value={f.canHelpWith} onChange={(e) => set("canHelpWith", e.target.value)} /></div>
        <div><Label htmlFor="ca">I&apos;m curious about…</Label><Textarea id="ca" rows={2} maxLength={400} value={f.curiousAbout} onChange={(e) => set("curiousAbout", e.target.value)} /></div>
      </div>
      <fieldset>
        <legend className="mb-2 text-sm font-medium">Languages you speak</legend>
        <div className="flex flex-wrap gap-2">
          {Object.entries(LANGUAGES).map(([code, name]) => <Chip key={code} active={f.languages.includes(code)} onClick={() => set("languages", toggle(f.languages, code))}>{name}</Chip>)}
        </div>
      </fieldset>
      <fieldset>
        <legend className="mb-2 text-sm font-medium">Ways you&apos;re comfortable talking</legend>
        <div className="flex flex-wrap gap-2">
          {(["text", "voice", "video"] as Format[]).map((x) => <Chip key={x} active={f.formats.includes(x)} onClick={() => set("formats", toggle(f.formats, x))} className="capitalize">{x}</Chip>)}
        </div>
        <p className="mt-1 text-xs text-muted">Video always needs both people to opt in during the session.</p>
      </fieldset>
      <fieldset>
        <legend className="mb-2 text-sm font-medium">Interests <span className="font-normal text-muted">— used for “Surprise me”</span></legend>
        <div className="flex flex-wrap gap-2">
          {INTEREST_OPTIONS.map((t) => <Chip key={t.id} active={f.interests.includes(t.id)} onClick={() => set("interests", toggle(f.interests, t.id))}>{t.name}</Chip>)}
        </div>
      </fieldset>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <Label htmlFor="len">Usual session length</Label>
          <Select id="len" value={f.sessionLengthMinutes} onChange={(e) => set("sessionLengthMinutes", Number(e.target.value))}>
            {[15, 20, 30, 45, 60].map((m) => <option key={m} value={m}>{m} minutes</option>)}
          </Select>
        </div>
        <div><Label htmlFor="tz">Time zone</Label><Input id="tz" value={f.timezone} maxLength={60} onChange={(e) => set("timezone", e.target.value)} /></div>
      </div>
      <div><Label htmlFor="cant" hint="(shown to people who might invite you)">Topics I can&apos;t advise on</Label><Textarea id="cant" rows={2} maxLength={400} value={f.cannotAdvise} onChange={(e) => set("cannotAdvise", e.target.value)} /></div>

      {onboarding && (
        <label className="flex items-start gap-3 rounded-2xl border border-line bg-card p-4 text-sm">
          <input type="checkbox" required className="mt-0.5 h-4 w-4 accent-[var(--color-indigo)]" checked={f.adultConfirmed} onChange={(e) => set("adultConfirmed", e.target.checked)} />
          <span>
            I&apos;m 18 or older and I&apos;ll treat people with respect.
            <span className="block text-muted">This pilot is for invited adults. A checkbox isn&apos;t real age verification — please don&apos;t join if you&apos;re under 18.</span>
          </span>
        </label>
      )}
      {err && <Notice tone="rose">{err}</Notice>}
      {ok && <Notice tone="teal">Saved.</Notice>}
      <Button type="submit" size="lg" disabled={pending}>{pending ? "Saving…" : onboarding ? "Join People" : "Save profile"}</Button>
    </form>
  );
}

export function HelperTopicsEditor({ initial }: { initial: HelperTopic[] }) {
  const router = useRouter();
  const [items, setItems] = useState(initial.map(({ topicId, kind, detail, welcomesBeginners }) => ({ topicId, kind, detail, welcomesBeginners })));
  const [draft, setDraft] = useState("");
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<{ tone: "rose" | "teal"; text: string } | null>(null);
  return (
    <div className="space-y-4">
      {items.length === 0 && <p className="text-sm text-muted">No topics yet. You won&apos;t be matched until you add one.</p>}
      <ul className="space-y-3">
        {items.map((it, i) => (
          <li key={it.topicId} className="rounded-2xl border border-line p-4">
            <div className="flex items-start justify-between gap-2">
              <p className="font-medium">{topicPath(it.topicId)}</p>
              <Button variant="ghost" size="sm" onClick={() => setItems(items.filter((_, j) => j !== i))}>Remove</Button>
            </div>
            <div className="mt-2 flex flex-wrap gap-2" role="group" aria-label="Kind of experience">
              <Chip active={it.kind === "lived"} onClick={() => setItems(items.map((x, j) => j === i ? { ...x, kind: "lived" } : x))}>Lived experience</Chip>
              <Chip active={it.kind === "professional"} onClick={() => setItems(items.map((x, j) => j === i ? { ...x, kind: "professional" } : x))}>Professional experience</Chip>
            </div>
            <Label htmlFor={`d-${i}`}><span className="sr-only">Describe your experience</span></Label>
            <Input id={`d-${i}`} className="mt-2" placeholder="In a sentence: what's your experience?" maxLength={300} value={it.detail} onChange={(e) => setItems(items.map((x, j) => j === i ? { ...x, detail: e.target.value } : x))} />
            <label className="mt-2 flex items-center gap-2 text-sm">
              <input type="checkbox" className="h-4 w-4 accent-[var(--color-teal)]" checked={it.welcomesBeginners} onChange={(e) => setItems(items.map((x, j) => j === i ? { ...x, welcomesBeginners: e.target.checked } : x))} />
              Happy to help complete beginners
            </label>
          </li>
        ))}
      </ul>
      <div className="rounded-2xl bg-paper-2/60 p-4">
        <p className="mb-2 text-sm font-medium">Add a topic</p>
        <TopicPicker value={draft} onChange={setDraft} idPrefix="ht" />
        <Button variant="secondary" size="sm" className="mt-3" disabled={!draft || items.some((x) => x.topicId === draft)}
          onClick={() => { setItems([...items, { topicId: draft, kind: "lived", detail: "", welcomesBeginners: true }]); setDraft(""); }}>Add {draft ? getTopic(draft)?.name : ""}</Button>
      </div>
      <p className="text-xs text-muted">“Professional experience” is self-described. People only marks a credential as reviewed after a moderator checks it, and only for that topic.</p>
      {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
      <Button disabled={pending} onClick={() => start(async () => { const r = await saveHelperTopics(items); setMsg(r.ok ? { tone: "teal", text: "Topics saved." } : { tone: "rose", text: r.error }); router.refresh(); })}>Save topics</Button>
    </div>
  );
}

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const SLOTS = [["Morning", 8, 12], ["Afternoon", 12, 17], ["Evening", 17, 22]] as const;

export function AvailabilityEditor({ initial, timezone }: { initial: AvailabilityWindow[]; timezone: string }) {
  const has = (d: number, s: number, e: number) => initial.some((w) => w.weekday === d && w.startMinute === s * 60 && w.endMinute === e * 60);
  const [grid, setGrid] = useState(() => DAYS.map((_, d) => SLOTS.map(([, s, e]) => has(d, s, e))));
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<string | null>(null);
  const custom = initial.filter((w) => !SLOTS.some(([, s, e]) => w.startMinute === s * 60 && w.endMinute === e * 60));
  return (
    <div>
      <p className="mb-3 text-sm text-muted">When you&apos;re usually free for scheduled sessions ({timezone}). This is separate from “available now”.</p>
      <div className="overflow-x-auto">
        <table className="text-sm">
          <thead><tr><th className="sr-only">Time</th>{DAYS.map((d) => <th key={d} className="px-1 pb-2 font-medium text-muted">{d}</th>)}</tr></thead>
          <tbody>
            {SLOTS.map(([label], si) => (
              <tr key={label}>
                <th scope="row" className="pr-2 text-left font-medium text-muted">{label}</th>
                {DAYS.map((d, di) => (
                  <td key={d} className="p-1">
                    <button type="button" aria-pressed={grid[di][si]} aria-label={`${d} ${label}`}
                      onClick={() => setGrid(grid.map((row, i) => i === di ? row.map((v, j) => j === si ? !v : v) : row))}
                      className={`h-9 w-10 rounded-lg border ${grid[di][si] ? "border-teal bg-teal text-white" : "border-line-2 bg-card"}`}>{grid[di][si] ? "✓" : ""}</button>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Button className="mt-4" disabled={pending} onClick={() => start(async () => {
        const windows = [
          ...grid.flatMap((row, d) => row.flatMap((on, si) => on ? [{ weekday: d, startMinute: SLOTS[si][1] * 60, endMinute: SLOTS[si][2] * 60 }] : [])),
          ...custom.map(({ weekday, startMinute, endMinute }) => ({ weekday, startMinute, endMinute })),
        ];
        const r = await saveAvailability(windows);
        setMsg(r.ok ? "Availability saved." : r.error);
      })}>Save availability</Button>
      {msg && <p role="status" className="mt-2 text-sm text-muted">{msg}</p>}
    </div>
  );
}

export function CredentialForm() {
  const router = useRouter();
  const [topicId, setTopicId] = useState("");
  const [title, setTitle] = useState("");
  const [issuer, setIssuer] = useState("");
  const [note, setNote] = useState("");
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<{ tone: "rose" | "teal"; text: string } | null>(null);
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); start(async () => {
      const r = await submitCredential({ topicId, title, issuer, evidenceNote: note });
      setMsg(r.ok ? { tone: "teal", text: "Submitted for review. A moderator will check it — until then it isn't shown as reviewed." } : { tone: "rose", text: r.error });
      if (r.ok) { setTitle(""); setIssuer(""); setNote(""); router.refresh(); }
    }); }}>
      <TopicPicker value={topicId} onChange={setTopicId} idPrefix="cr" />
      <div className="grid gap-3 sm:grid-cols-2">
        <div><Label htmlFor="ct">Credential</Label><Input id="ct" required maxLength={120} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Certified teacher" /></div>
        <div><Label htmlFor="ci">Issued by</Label><Input id="ci" maxLength={120} value={issuer} onChange={(e) => setIssuer(e.target.value)} /></div>
      </div>
      <div><Label htmlFor="cn" hint="(no documents or ID numbers here)">How could a moderator confirm it?</Label><Textarea id="cn" rows={2} maxLength={600} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. public registry entry, or happy to show it on a call" /></div>
      {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
      <Button type="submit" variant="secondary" disabled={pending || !topicId || !title.trim()}>Submit for review</Button>
    </form>
  );
}
