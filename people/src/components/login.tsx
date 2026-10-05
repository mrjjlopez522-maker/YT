"use client";

import { useState, useTransition } from "react";
import { demoSignIn, sendMagicLink } from "@/app/actions";
import { Avatar, Button, Input, Label, Notice } from "./ui";

export function DemoPersonas({ personas }: { personas: { id: string; name: string; color: string; blurb: string }[] }) {
  const [pending, start] = useTransition();
  return (
    <div>
      <ul className="grid gap-3 sm:grid-cols-2">
        {personas.map((p) => (
          <li key={p.id}>
            <button disabled={pending} onClick={() => start(() => demoSignIn(p.id))}
              className="flex w-full items-center gap-3 rounded-2xl border border-line bg-card p-4 text-left transition-all hover:-translate-y-0.5 hover:border-line-2 hover:shadow-[var(--shadow-soft)]">
              <Avatar name={p.name} color={p.color} size={44} />
              <span><span className="block font-semibold">{p.name}</span><span className="block text-sm text-muted">{p.blurb}</span></span>
            </button>
          </li>
        ))}
      </ul>
      <button disabled={pending} onClick={() => start(() => demoSignIn("new"))} className="mt-4 text-sm text-indigo underline-offset-2 hover:underline">
        Or create a new demo person and go through onboarding
      </button>
    </div>
  );
}

export function EmailLogin() {
  const [email, setEmail] = useState("");
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<{ tone: "teal" | "rose"; text: string } | null>(null);
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); start(async () => {
      const r = await sendMagicLink(email, window.location.origin);
      setMsg(r.ok ? { tone: "teal", text: "Check your email for a sign-in link." } : { tone: "rose", text: r.error });
    }); }}>
      <div><Label htmlFor="em">Email</Label><Input id="em" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
      <Button type="submit" disabled={pending} className="w-full">{pending ? "Sending…" : "Email me a sign-in link"}</Button>
      {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
    </form>
  );
}
