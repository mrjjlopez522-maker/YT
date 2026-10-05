import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowRight, Clock } from "lucide-react";
import { LiveRefresher } from "@/components/live";
import { ExperienceBadge, PersonLine, VerifiedList } from "@/components/person";
import { AutoMatchButton, CancelRequestButton, Countdown, InviteButton, NoMatchOptions, WithdrawButton } from "@/components/requests/actions";
import { Badge, Card, LinkButton, Notice, SectionTitle } from "@/components/ui";
import { languageName } from "@/lib/domain/languages";
import { intentLabel, RESPECT_NOTE } from "@/lib/domain/prompts";
import { isPerspective, topicPath } from "@/lib/domain/topics";
import { requireViewer } from "@/lib/server/auth";
import { getService } from "@/lib/server/runtime";
import { isAppError } from "@/lib/server/service";
import { RequestStatusBadge } from "@/components/requests/status";
import { LocalTime } from "@/components/local-time";

export const metadata = { title: "Request" };

export default async function RequestPage(props: PageProps<"/requests/[id]">) {
  const { id } = await props.params;
  const { viewer } = await requireViewer();
  const svc = getService();
  const view = await svc.getRequest(viewer, id).catch((e) => { if (isAppError(e)) notFound(); throw e; });
  const { request: r, invitations, session, responses } = view;
  const matchable = ["open", "async_open", "answered"].includes(r.status);
  const found = matchable ? await svc.findMatches(viewer, id) : null;
  const pending = invitations.find((i) => i.status === "pending");
  const last = [...invitations].reverse().find((i) => i.status !== "pending");

  const lastNote = last && matchable && {
    declined: `${last.helper?.displayName ?? "They"} can't make it this time — no reason needed. Here are other people who fit.`,
    expired: `${last.helper?.displayName ?? "They"} didn't reply in time, so the invitation expired.`,
    unavailable: `${last.helper?.displayName ?? "That person"} became unavailable before replying.`,
    cancelled: "You withdrew the last invitation.",
    accepted: null,
  }[last.status as "declined" | "expired" | "unavailable" | "cancelled" | "accepted"];

  return (
    <div className="mx-auto max-w-3xl">
      <LiveRefresher topics={[`user:${viewer.id}`]} />
      <Link href="/requests" className="text-sm text-muted hover:text-ink">← My requests</Link>

      <Card className="mt-3 p-5 sm:p-6">
        <div className="flex flex-wrap items-center gap-2">
          <RequestStatusBadge status={r.status} />
          <Badge>{intentLabel(r.intent)}</Badge>
          <Badge>{topicPath(r.topicId)}</Badge>
        </div>
        <h1 className="mt-3 font-display text-2xl font-semibold leading-snug sm:text-[28px]">{r.question}</h1>
        <p className="mt-2 text-sm text-muted">
          {languageName(r.language)} · {r.formats.join(", ")} · {r.timing === "now" ? "Now" : <>Around <LocalTime iso={r.preferredTime!} /></>}
          {r.broadened.length > 0 && <> · widened: {r.broadened.join(", ")}</>}
        </p>
        {r.context && <p className="prewrap mt-3 text-sm text-ink-2">{r.context}</p>}
        {r.clarificationAnswer && <p className="mt-2 text-sm text-ink-2"><span className="text-muted">{r.clarificationQuestion}</span> {r.clarificationAnswer}</p>}
        {["open", "waiting", "async_open", "answered"].includes(r.status) && (
          <div className="mt-4 border-t border-line pt-3"><CancelRequestButton requestId={r.id} /></div>
        )}
      </Card>

      {isPerspective(r.topicId) && <Notice tone="indigo" className="mt-4">{RESPECT_NOTE}</Notice>}

      {r.status === "matched" && session && (
        <Card className="mt-6 border-teal/30 bg-teal-soft p-5">
          <p className="font-semibold text-teal">You&apos;re matched.</p>
          <p className="mt-1 text-sm">{session.status === "scheduled" ? <>Booked for <LocalTime iso={session.scheduledAt!} />.</> : "Your session is open now."}</p>
          <LinkButton href={`/sessions/${session.id}`} variant="teal" className="mt-3">Go to session <ArrowRight size={16} aria-hidden /></LinkButton>
        </Card>
      )}

      {r.status === "closed" && session && (
        <Notice className="mt-6" title="This session has finished.">
          <Link className="underline" href={`/sessions/${session.id}/wrap`}>See notes and next steps</Link>
        </Notice>
      )}
      {r.status === "cancelled" && <Notice className="mt-6">You cancelled this request.</Notice>}

      {r.status === "waiting" && pending && (
        <Card className="mt-6 p-5" aria-live="polite">
          <SectionTitle>Waiting for a reply</SectionTitle>
          {pending.helper && <PersonLine p={pending.helper} />}
          <p className="mt-4 flex items-center gap-2 text-sm text-ink-2">
            <Clock size={16} aria-hidden />
            {pending.auto ? "Matched automatically. " : ""}They have <strong><Countdown until={pending.expiresAt} /></strong> to accept. If they can&apos;t, {r.autoMatch ? "we'll ask the next person who fits." : "you can ask someone else."}
          </p>
          <p className="mt-1 text-xs text-muted">The session only starts once they accept. We don&apos;t show whether they&apos;ve seen it.</p>
          <div className="mt-3"><WithdrawButton invitationId={pending.id} /></div>
        </Card>
      )}

      {lastNote && <Notice tone="amber" className="mt-6">{lastNote}</Notice>}

      {(r.status === "async_open" || r.status === "answered") && (
        <section className="mt-8">
          <SectionTitle>Written replies</SectionTitle>
          {responses.length === 0 ? (
            <Notice>Your question is waiting for a written reply. People whose topics and language fit can see it — not the public.</Notice>
          ) : (
            <div className="space-y-3">
              {responses.map((resp) => (
                <Card key={resp.id} className="p-5">
                  {resp.helper && <PersonLine p={resp.helper} sub={<>Replied <LocalTime iso={resp.createdAt} /> · personal perspective</>} />}
                  <p className="prewrap mt-3 text-[15px] leading-relaxed">{resp.body}</p>
                  {resp.helper && !invitations.some((i) => i.helperId === resp.helperId) && !pending && (
                    <div className="mt-3"><InviteButton requestId={r.id} helperId={resp.helperId} name={resp.helper.displayName} /></div>
                  )}
                </Card>
              ))}
            </div>
          )}
        </section>
      )}

      {found && !pending && (
        <section className="mt-8" aria-labelledby="matches-h">
          <SectionTitle aside={found.matches.length > 0 && <AutoMatchButton requestId={r.id} />}>
            <span id="matches-h">{found.matches.length ? "People who could help" : "Nobody available right now"}</span>
          </SectionTitle>
          {found.matches.length > 0 ? (
            <>
              <ul className="space-y-3">
                {found.matches.map((m) => (
                  <li key={m.helperId}>
                    <Card className="p-5">
                      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                        <PersonLine p={m.profile} />
                        <InviteButton requestId={r.id} helperId={m.helperId} name={m.profile.displayName} />
                      </div>
                      <ul className="mt-4 space-y-1.5 text-sm text-ink-2">
                        {m.reasons.map((why) => <li key={why} className="flex gap-2"><span aria-hidden className="text-teal">•</span>{why}</li>)}
                      </ul>
                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        <ExperienceBadge kind={m.topic.kind} />
                        {m.topic.detail && <span className="text-sm text-muted">“{m.topic.detail}”</span>}
                      </div>
                      {m.verified && <div className="mt-2"><VerifiedList p={m.profile} /></div>}
                      {m.profile.cannotAdvise && <p className="mt-2 text-xs text-muted">Can&apos;t advise on: {m.profile.cannotAdvise}</p>}
                    </Card>
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-xs leading-relaxed text-muted">
                Ordered by fit with your topic, language, format and timing — not a rating of anyone&apos;s expertise or accuracy.
                {found.eligibleCount > found.matches.length && ` ${found.eligibleCount - found.matches.length} more people also fit.`}
              </p>
            </>
          ) : (
            <>
              <p className="mb-4 text-sm text-muted">Nobody who fits your topic, language and format is available{r.timing === "now" ? " right now" : " at that time"}. We won&apos;t pretend otherwise. Here&apos;s what you can do:</p>
              <NoMatchOptions requestId={r.id} broaden={found.broaden} canLeave={r.status === "open"} />
            </>
          )}
          {found.matches.length > 0 && r.status === "open" && (
            <details className="mt-6 rounded-2xl border border-line bg-card/60 p-4 text-sm">
              <summary className="cursor-pointer font-medium">None of these feel right?</summary>
              <div className="mt-4"><NoMatchOptions requestId={r.id} broaden={found.broaden} canLeave /></div>
            </details>
          )}
        </section>
      )}
    </div>
  );
}
