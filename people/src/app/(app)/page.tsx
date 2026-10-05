import Link from "next/link";
import { ArrowRight, Radio } from "lucide-react";
import { Composer } from "@/components/home/composer";
import { Card } from "@/components/ui";
import { rootTopics } from "@/lib/domain/topics";
import { requireViewer } from "@/lib/server/auth";
import { getService } from "@/lib/server/runtime";

export default async function Home() {
  const { viewer, profile } = await requireViewer();
  const svc = getService();
  const [sessions, requests, badges] = await Promise.all([svc.listMySessions(viewer), svc.listMyRequests(viewer), svc.badges(viewer)]);
  const live = sessions.filter((s) => s.session.status === "active");
  const waiting = requests.filter((r) => r.status === "waiting");
  const categories = rootTopics().filter((t) => t.sensitivity !== "high_stakes");

  return (
    <div className="mx-auto max-w-3xl">
      {(live.length > 0 || badges.invites > 0 || waiting.length > 0) && (
        <div className="mb-8 grid gap-3">
          {live.map((s) => (
            <Link key={s.session.id} href={`/sessions/${s.session.id}`} className="block">
              <Card className="flex items-center gap-3 border-teal/30 bg-teal-soft p-4 hover:brightness-[0.98]">
                <Radio size={18} className="text-teal" aria-hidden />
                <p className="flex-1 text-sm"><strong>In a session</strong> with {s.other?.displayName ?? "someone"} — {s.request.question}</p>
                <span className="text-sm font-semibold text-teal">Rejoin</span>
              </Card>
            </Link>
          ))}
          {badges.invites > 0 && (
            <Link href="/helping" className="block">
              <Card className="flex items-center gap-3 p-4 hover:border-line-2">
                <span className="h-2.5 w-2.5 rounded-full bg-indigo" aria-hidden />
                <p className="flex-1 text-sm"><strong>{badges.invites} {badges.invites === 1 ? "person is" : "people are"} asking for your help.</strong> Accept or decline — either is fine.</p>
                <ArrowRight size={16} aria-hidden />
              </Card>
            </Link>
          )}
          {waiting.map((r) => (
            <Link key={r.id} href={`/requests/${r.id}`} className="block">
              <Card className="flex items-center gap-3 p-4 hover:border-line-2">
                <span className="h-2.5 w-2.5 animate-pulse-dot rounded-full bg-amber-ink" aria-hidden />
                <p className="flex-1 truncate text-sm"><strong>Waiting for a reply</strong> · {r.question}</p>
                <ArrowRight size={16} aria-hidden />
              </Card>
            </Link>
          ))}
        </div>
      )}

      <Composer firstName={profile.displayName.split(" ")[0]} />

      <section className="mt-12" aria-labelledby="browse">
        <h2 id="browse" className="mb-3 text-xs font-medium uppercase tracking-wide text-muted">Or start from a topic</h2>
        <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {categories.map((t) => (
            <li key={t.id}>
              <Link
                href={`/requests/new?topic=${t.id}`}
                className="flex h-full flex-col rounded-2xl border border-line bg-card/60 px-3.5 py-3 text-sm hover:border-line-2 hover:bg-card"
              >
                <span className="font-medium">{t.name}</span>
                <span className="mt-0.5 line-clamp-2 text-xs text-muted">{t.description}</span>
              </Link>
            </li>
          ))}
        </ul>
        <p className="mt-4 text-xs leading-relaxed text-muted">
          Helpers share their own experience. Some have a credential reviewed by People for a specific topic — it&apos;s
          labelled when they do. Nobody here is guaranteed to be right, and medical, legal and investment advice isn&apos;t offered.
        </p>
      </section>
    </div>
  );
}
