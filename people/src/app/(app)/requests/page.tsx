import Link from "next/link";
import { LiveRefresher } from "@/components/live";
import { LocalTime } from "@/components/local-time";
import { RequestStatusBadge } from "@/components/requests/status";
import { RequestsTabs } from "@/components/segmented";
import { Card, EmptyState, LinkButton, PageHeader } from "@/components/ui";
import { intentLabel } from "@/lib/domain/prompts";
import { getTopic } from "@/lib/domain/topics";
import { requireViewer } from "@/lib/server/auth";
import { getService } from "@/lib/server/runtime";

export const metadata = { title: "My requests" };

export default async function Requests() {
  const { viewer } = await requireViewer();
  const [requests, badges] = await Promise.all([getService().listMyRequests(viewer), getService().badges(viewer)]);
  const active = requests.filter((r) => !["closed", "cancelled"].includes(r.status));
  const past = requests.filter((r) => ["closed", "cancelled"].includes(r.status));
  return (
    <div className="mx-auto max-w-3xl">
      <LiveRefresher topics={[`user:${viewer.id}`]} />
      <RequestsTabs active="mine" invites={badges.invites} />
      <PageHeader title="My requests" subtitle="Questions you've asked and where they stand." action={<LinkButton href="/">New request</LinkButton>} />
      {requests.length === 0 && (
        <EmptyState title="Nothing asked yet" action={<LinkButton href="/">Ask something</LinkButton>}>
          When you ask a question, it shows up here with who you&apos;ve invited and what happened.
        </EmptyState>
      )}
      {[["Active", active], ["Earlier", past]].map(([label, list]) =>
        (list as typeof requests).length > 0 && (
          <section key={label as string} className="mb-8">
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted">{label as string}</h2>
            <ul className="space-y-2">
              {(list as typeof requests).map((r) => (
                <li key={r.id}>
                  <Link href={`/requests/${r.id}`} className="block">
                    <Card className="p-4 transition-colors hover:border-line-2">
                      <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                        <RequestStatusBadge status={r.status} />
                        <span>{intentLabel(r.intent)} · {getTopic(r.topicId)?.name}</span>
                        <span className="ml-auto"><LocalTime iso={r.createdAt} mode="date" /></span>
                      </div>
                      <p className="mt-2 font-medium leading-snug">{r.question}</p>
                    </Card>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ),
      )}
    </div>
  );
}
