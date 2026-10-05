import Link from "next/link";
import { LiveRefresher } from "@/components/live";
import { LocalTime } from "@/components/local-time";
import { SessionStatusBadge } from "@/components/requests/status";
import { Avatar, Card, EmptyState, LinkButton, PageHeader, SectionTitle } from "@/components/ui";
import { intentLabel } from "@/lib/domain/prompts";
import { requireViewer } from "@/lib/server/auth";
import { getService } from "@/lib/server/runtime";

export const metadata = { title: "Sessions" };

export default async function Sessions() {
  const { viewer } = await requireViewer();
  const all = await getService().listMySessions(viewer);
  const groups = [
    { title: "Live now", items: all.filter((s) => s.session.status === "active") },
    { title: "Upcoming", items: all.filter((s) => s.session.status === "scheduled") },
    { title: "Past", items: all.filter((s) => s.session.status === "ended" || s.session.status === "cancelled") },
  ];
  return (
    <div className="mx-auto max-w-3xl">
      <LiveRefresher topics={[`user:${viewer.id}`]} />
      <PageHeader title="Sessions" subtitle="Conversations you've had or have coming up." />
      {all.length === 0 && (
        <EmptyState title="No sessions yet" action={<LinkButton href="/">Ask something</LinkButton>}>
          A session opens when someone accepts your request — or you accept theirs.
        </EmptyState>
      )}
      {groups.filter((g) => g.items.length).map((g) => (
        <section key={g.title} className="mb-8">
          <SectionTitle>{g.title}</SectionTitle>
          <ul className="space-y-2">
            {g.items.map(({ session: s, request: r, other, otherRole }) => (
              <li key={s.id}>
                <Link href={s.status === "ended" ? `/sessions/${s.id}/wrap` : `/sessions/${s.id}`} className="block">
                  <Card className="flex items-center gap-3 p-4 hover:border-line-2">
                    {other ? <Avatar name={other.displayName} color={other.avatarColor} size={36} /> : <Avatar name="?" color="#a8a29e" size={36} />}
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium">{r.question}</p>
                      <p className="text-sm text-muted">
                        {other?.displayName ?? "Someone"} {otherRole === "helper" ? "helped you" : "asked you"} · {intentLabel(r.intent)} ·{" "}
                        <LocalTime iso={s.scheduledAt ?? s.startedAt ?? s.createdAt} mode="date" />
                      </p>
                    </div>
                    <SessionStatusBadge status={s.status} />
                  </Card>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
