import { CredentialActions, PeopleSearch, ReportActions, SuspendControl } from "@/components/moderation";
import { LocalTime } from "@/components/local-time";
import { Badge, Card, EmptyState, Notice, PageHeader, SectionTitle } from "@/components/ui";
import { topicPath } from "@/lib/domain/topics";
import { requireViewer } from "@/lib/server/auth";
import { getService } from "@/lib/server/runtime";
import { isAppError } from "@/lib/server/service";

export const metadata = { title: "Moderation" };

const REASON: Record<string, string> = {
  harassment: "Harassment", inappropriate_media: "Inappropriate media", spam: "Spam", unsafe_advice: "Unsafe advice",
  impersonation: "Impersonation", other: "Other",
};

export default async function Moderation() {
  const { viewer } = await requireViewer();
  let data;
  try {
    data = await getService().modOverview(viewer); // role re-checked from the database
  } catch (e) {
    if (isAppError(e) && e.code === "forbidden") return <Notice tone="rose" title="Moderators only">You don&apos;t have access to this page.</Notice>;
    throw e;
  }
  const name = (id: string | null) => (id ? data.names[id] ?? "Unknown" : "—");
  const open = data.reports.filter((r) => r.status === "open");
  const closed = data.reports.filter((r) => r.status !== "open");
  const pendingCreds = data.credentials.filter((c) => c.status === "pending");
  return (
    <div className="mx-auto max-w-4xl space-y-10">
      <PageHeader title="Moderation" subtitle="Reports, suspensions and credential reviews. Every action is logged." />
      <Notice tone="amber" title="What this tool does not do">
        There is no automated media moderation: LiveKit does not detect nudity or abuse, and calls aren&apos;t recorded. Reports rely on what people describe and on session text.
      </Notice>

      <section>
        <SectionTitle>Open reports ({open.length})</SectionTitle>
        {open.length === 0 ? <EmptyState title="No open reports" /> : (
          <ul className="space-y-3">
            {open.map((r) => (
              <li key={r.id}>
                <Card className="p-5">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <Badge tone="rose">{REASON[r.reason]}</Badge>
                    <span><strong>{name(r.reportedUserId)}</strong> reported by {name(r.reporterId)}</span>
                    <span className="ml-auto text-xs text-muted"><LocalTime iso={r.createdAt} /></span>
                  </div>
                  {r.details && <p className="prewrap mt-2 text-sm">{r.details}</p>}
                  {r.sessionId && <p className="mt-1 text-xs text-muted">Linked to a session.</p>}
                  <ReportActions reportId={r.id} open />
                  <div className="mt-3 border-t border-line pt-3"><SuspendControl userId={r.reportedUserId} suspended={data.suspended.some((s) => s.id === r.reportedUserId)} name={name(r.reportedUserId)} /></div>
                </Card>
              </li>
            ))}
          </ul>
        )}
        {closed.length > 0 && <p className="mt-3 text-sm text-muted">{closed.length} resolved report(s) — see the audit log.</p>}
      </section>

      <section>
        <SectionTitle>Credential reviews ({pendingCreds.length} pending)</SectionTitle>
        <ul className="space-y-3">
          {data.credentials.map((c) => (
            <li key={c.id}>
              <Card className="p-5">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <Badge tone={c.status === "verified" ? "teal" : c.status === "pending" ? "amber" : "rose"}>{c.status}</Badge>
                  <strong>{c.title}</strong>{c.issuer && <span className="text-muted">({c.issuer})</span>}
                  <span className="text-muted">· {name(c.userId)} · {topicPath(c.topicId)}</span>
                </div>
                {c.evidenceNote && <p className="mt-1 text-sm text-ink-2">How to confirm: {c.evidenceNote}</p>}
                <CredentialActions id={c.id} status={c.status} />
              </Card>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-muted">Verification is manual in this MVP. Verify only what you actually confirmed, and only for the listed topic.</p>
      </section>

      <section>
        <SectionTitle>People</SectionTitle>
        <Card className="p-5">
          {data.suspended.length > 0 && (
            <div className="mb-4">
              <p className="mb-2 text-sm font-medium">Suspended</p>
              <ul className="space-y-2">{data.suspended.map((p) => <li key={p.id}><SuspendControl userId={p.id} suspended name={p.displayName} /></li>)}</ul>
            </div>
          )}
          <PeopleSearch />
        </Card>
      </section>

      <section>
        <SectionTitle>Audit log</SectionTitle>
        <Card className="overflow-x-auto p-0">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-line text-xs uppercase tracking-wide text-muted">
              <tr><th className="px-4 py-2 font-medium">When</th><th className="px-4 py-2 font-medium">Moderator</th><th className="px-4 py-2 font-medium">Action</th><th className="px-4 py-2 font-medium">Person</th><th className="px-4 py-2 font-medium">Reason</th></tr>
            </thead>
            <tbody>
              {data.audit.map((a) => (
                <tr key={a.id} className="border-b border-line last:border-0">
                  <td className="whitespace-nowrap px-4 py-2 text-muted"><LocalTime iso={a.createdAt} /></td>
                  <td className="px-4 py-2">{name(a.moderatorId)}</td>
                  <td className="px-4 py-2"><code className="text-xs">{a.action}</code></td>
                  <td className="px-4 py-2">{name(a.targetUserId)}</td>
                  <td className="px-4 py-2 text-ink-2">{a.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <p className="mt-2 text-xs text-muted">Append-only: the database rejects edits and deletions.</p>
      </section>
    </div>
  );
}
