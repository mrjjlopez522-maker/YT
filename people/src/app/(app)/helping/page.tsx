import Link from "next/link";
import { AvailabilityToggle, InvitationButtons } from "@/components/helping";
import { LiveRefresher } from "@/components/live";
import { LocalTime } from "@/components/local-time";
import { PersonLine } from "@/components/person";
import { Countdown } from "@/components/requests/actions";
import { SessionStatusBadge } from "@/components/requests/status";
import { RequestsTabs } from "@/components/segmented";
import { Badge, Card, EmptyState, LinkButton, PageHeader, SectionTitle } from "@/components/ui";
import { languageName } from "@/lib/domain/languages";
import { intentLabel } from "@/lib/domain/prompts";
import { topicPath } from "@/lib/domain/topics";
import { requireViewer } from "@/lib/server/auth";
import { getService } from "@/lib/server/runtime";

export const metadata = { title: "Helping" };

const LEVEL: Record<string, string> = { new: "New to this", some: "Some experience", experienced: "Experienced" };

export default async function Helping() {
  const { viewer } = await requireViewer();
  const data = await getService().inbox(viewer);
  return (
    <div className="mx-auto max-w-3xl">
      <LiveRefresher topics={[`user:${viewer.id}`]} />
      <RequestsTabs active="helping" invites={data.invitations.length} />
      <PageHeader title="Helping" subtitle="People who asked for you, and questions you could answer." action={<LinkButton variant="secondary" href="/profile/edit#helping">Topics &amp; availability</LinkButton>} />

      <AvailabilityToggle until={data.availableUntil} />

      <section className="mt-8" aria-labelledby="inv-h">
        <SectionTitle><span id="inv-h">Asking for you</span></SectionTitle>
        {data.invitations.length === 0 ? (
          <EmptyState title="No requests right now">New invitations appear here instantly. Declining is always fine — they&apos;ll be matched with someone else.</EmptyState>
        ) : (
          <ul className="space-y-3">
            {data.invitations.map(({ invitation: inv, request: r, requester }) => (
              <li key={inv.id}>
                <Card className="animate-rise p-5">
                  {requester && <PersonLine p={requester} />}
                  <p className="mt-4 font-display text-xl leading-snug">{r.question}</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Badge tone="indigo">{intentLabel(r.intent)}</Badge>
                    <Badge>{topicPath(r.topicId)}</Badge>
                    <Badge>{languageName(r.language)}</Badge>
                    <Badge>{r.formats.join(" / ")}</Badge>
                    {r.experienceLevel && <Badge>{LEVEL[r.experienceLevel]}</Badge>}
                  </div>
                  {r.context && <p className="prewrap mt-3 text-sm text-ink-2">{r.context}</p>}
                  {r.clarificationAnswer && <p className="mt-2 text-sm"><span className="text-muted">{r.clarificationQuestion}</span> {r.clarificationAnswer}</p>}
                  <p className="mt-3 text-sm text-muted">
                    {inv.proposedTime ? <>For <LocalTime iso={inv.proposedTime} />. </> : "Wants to talk now. "}
                    Expires in <Countdown until={inv.expiresAt} />.
                  </p>
                  <div className="mt-4"><InvitationButtons invitationId={inv.id} /></div>
                </Card>
              </li>
            ))}
          </ul>
        )}
        {data.recent.length > 0 && (
          <p className="mt-3 text-xs text-muted">
            Recently closed without a session: {data.recent.map((i) => ({ expired: "expired", cancelled: "withdrawn by them", unavailable: "no longer available", declined: "declined", accepted: "accepted", pending: "" }[i.status])).join(", ")}.
          </p>
        )}
      </section>

      <section className="mt-10" aria-labelledby="up-h">
        <SectionTitle><span id="up-h">Upcoming &amp; live sessions</span></SectionTitle>
        {data.sessions.length === 0 ? <p className="text-sm text-muted">None.</p> : (
          <ul className="space-y-2">
            {data.sessions.map(({ session: s, request: r }) => (
              <li key={s.id}>
                <Link href={`/sessions/${s.id}`} className="block">
                  <Card className="flex items-center gap-3 p-4 hover:border-line-2">
                    <SessionStatusBadge status={s.status} />
                    <span className="flex-1 truncate text-sm">{r.question}</span>
                    {s.scheduledAt && <span className="text-xs text-muted"><LocalTime iso={s.scheduledAt} /></span>}
                  </Card>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="mt-10" aria-labelledby="async-h">
        <SectionTitle><span id="async-h">Questions waiting for a written answer</span></SectionTitle>
        {data.asyncQuestions.length === 0 ? (
          <p className="text-sm text-muted">Nothing in your topics right now.</p>
        ) : (
          <ul className="space-y-2">
            {data.asyncQuestions.map(({ request: r, answeredByMe }) => (
              <li key={r.id}>
                <Link href={`/helping/questions/${r.id}`} className="block">
                  <Card className="p-4 hover:border-line-2">
                    <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                      <span>{topicPath(r.topicId)}</span>
                      {answeredByMe && <Badge tone="teal">You replied</Badge>}
                    </div>
                    <p className="mt-1 font-medium">{r.question}</p>
                  </Card>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
