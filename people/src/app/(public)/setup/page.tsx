import { CheckCircle2, CircleDashed } from "lucide-react";
import { ResetDemo } from "@/components/reset-demo";
import { Badge, Card, Notice } from "@/components/ui";
import { serverConfig } from "@/lib/config";

export const metadata = { title: "Setup & status" };

function Row({ ok, title, children }: { ok: boolean; title: string; children: React.ReactNode }) {
  return (
    <li className="flex gap-3 border-b border-line py-4 last:border-0">
      {ok ? <CheckCircle2 className="mt-0.5 shrink-0 text-teal" size={20} aria-hidden /> : <CircleDashed className="mt-0.5 shrink-0 text-muted" size={20} aria-hidden />}
      <div>
        <p className="flex flex-wrap items-center gap-2 font-semibold">{title} <Badge tone={ok ? "teal" : "neutral"}>{ok ? "Configured" : "Not configured"}</Badge></p>
        <div className="mt-1 text-sm text-ink-2">{children}</div>
      </div>
    </li>
  );
}

export default function Setup() {
  const c = serverConfig();
  return (
    <div className="space-y-6">
      <h1 className="font-display text-4xl font-semibold">Setup &amp; status</h1>
      <Notice tone={c.mode === "demo" ? "amber" : "teal"} title={c.mode === "demo" ? "Running in demo mode" : "Running in live mode"}>
        {c.mode === "demo"
          ? "Data lives in this server's memory and is seeded with fictional sample people. It resets when the server restarts. Nobody real receives your requests."
          : "Accounts, requests and sessions are stored in your Supabase Postgres database with row-level security."}
      </Notice>
      <Card className="px-5">
        <ul>
          <Row ok={c.supabase.configured} title="Supabase (accounts, database, realtime)">
            Needs <code>NEXT_PUBLIC_SUPABASE_URL</code>, <code>NEXT_PUBLIC_SUPABASE_ANON_KEY</code> and the server-only <code>DATABASE_URL</code>.
            Without it: demo personas instead of email sign-in, in-memory data, and server-sent events instead of Supabase Realtime.
          </Row>
          <Row ok={c.livekit.configured} title="LiveKit (voice and video)">
            Needs <code>LIVEKIT_URL</code>, <code>LIVEKIT_API_KEY</code>, <code>LIVEKIT_API_SECRET</code>. Without it, sessions are text-only and the
            call panel says so — calls are never simulated. Calls are not recorded or transcribed.
          </Row>
          <Row ok={c.ai.configured} title="AI-assisted topic suggestions (optional)">
            Needs <code>ANTHROPIC_API_KEY</code>. Without it, topic suggestions use deterministic keyword matching. Either way, people confirm or correct the topic.
          </Row>
        </ul>
      </Card>
      <Card className="p-5">
        <h2 className="font-semibold">Not part of this MVP</h2>
        <p className="mt-1 text-sm text-ink-2">
          Payments and paid expert sessions, credits, group rooms, translation, automated credential checks, recording and transcription,
          automated media moderation, and native apps. None of these are simulated in the app.
        </p>
      </Card>
      {c.mode === "demo" && <ResetDemo />}
      <p className="text-sm text-muted">Full instructions: <code>people/README.md</code> and <code>people/docs/</code> in the repository.</p>
    </div>
  );
}
