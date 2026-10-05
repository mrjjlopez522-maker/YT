import Link from "next/link";
import { DeleteTakeaway, NewTakeaway } from "@/components/learning";
import { LocalTime } from "@/components/local-time";
import { Card, EmptyState, PageHeader, SectionTitle } from "@/components/ui";
import { intentLabel } from "@/lib/domain/prompts";
import { requireViewer } from "@/lib/server/auth";
import { getService } from "@/lib/server/runtime";

export const metadata = { title: "My learning" };

export default async function Learning() {
  const { viewer } = await requireViewer();
  const svc = getService();
  const [takeaways, sessions] = await Promise.all([svc.listTakeaways(viewer), svc.listMySessions(viewer)]);
  const past = sessions.filter((s) => s.session.status === "ended");
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="My learning" subtitle="Takeaways you chose to keep. Private to you." action={<NewTakeaway />} />
      {takeaways.length === 0 ? (
        <EmptyState title="Nothing saved yet">At the end of a session you can save the notes and next steps you agreed on. They&apos;ll collect here.</EmptyState>
      ) : (
        <ul className="space-y-4">
          {takeaways.map((t) => (
            <li key={t.id}>
              <Card className="p-5">
                <div className="flex items-start justify-between gap-3">
                  <h2 className="font-display text-lg font-semibold leading-snug">{t.title}</h2>
                  <DeleteTakeaway id={t.id} />
                </div>
                <p className="text-xs text-muted"><LocalTime iso={t.createdAt} mode="date" />{t.sessionId && <> · <Link className="underline" href={`/sessions/${t.sessionId}/wrap`}>from a session</Link></>}</p>
                {t.body && <p className="prewrap mt-3 text-[15px] leading-relaxed">{t.body}</p>}
                {t.nextSteps && (
                  <div className="mt-3 rounded-xl bg-teal-soft p-3">
                    <p className="text-xs font-semibold uppercase tracking-wide text-teal">Next steps</p>
                    <p className="prewrap mt-1 text-sm">{t.nextSteps}</p>
                  </div>
                )}
              </Card>
            </li>
          ))}
        </ul>
      )}
      {past.length > 0 && (
        <section className="mt-10">
          <SectionTitle>Past sessions</SectionTitle>
          <ul className="space-y-2">
            {past.map(({ session: s, request: r, other }) => (
              <li key={s.id}>
                <Link href={`/sessions/${s.id}/wrap`} className="block">
                  <Card className="p-4 hover:border-line-2">
                    <p className="font-medium">{r.question}</p>
                    <p className="text-sm text-muted">{intentLabel(r.intent)} with {other?.displayName ?? "someone"} · <LocalTime iso={s.endedAt ?? s.createdAt} mode="date" /></p>
                  </Card>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
