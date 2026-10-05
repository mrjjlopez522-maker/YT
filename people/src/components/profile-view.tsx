import { languageName } from "@/lib/domain/languages";
import { topicPath } from "@/lib/domain/topics";
import type { PublicProfile } from "@/lib/server/service";
import { ExperienceBadge, VerifiedList } from "./person";
import { Avatar, Badge, Card, SectionTitle } from "./ui";

export function ProfileView({ p, actions }: { p: PublicProfile; actions?: React.ReactNode }) {
  return (
    <div className="space-y-5">
      <Card className="p-6">
        <div className="flex flex-wrap items-start gap-4">
          <Avatar name={p.displayName} color={p.avatarColor} size={64} />
          <div className="min-w-0 flex-1">
            <h1 className="font-display text-3xl font-semibold">{p.displayName}</h1>
            <p className="text-sm text-muted">{[p.locationBroad, p.timezone].filter(Boolean).join(" · ")}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {p.availableNow && <Badge tone="teal">Available now</Badge>}
              {p.isModerator && <Badge tone="indigo">People team</Badge>}
              {p.languages.map((l) => <Badge key={l}>{languageName(l)}</Badge>)}
              {p.formats.map((f) => <Badge key={f} className="capitalize">{f}</Badge>)}
            </div>
          </div>
          {actions}
        </div>
        {p.intro && <p className="mt-4 text-[15px] leading-relaxed">{p.intro}</p>}
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          {p.canHelpWith && <div><p className="text-xs font-semibold uppercase tracking-wide text-muted">I can help with</p><p className="mt-1 text-sm">{p.canHelpWith}</p></div>}
          {p.curiousAbout && <div><p className="text-xs font-semibold uppercase tracking-wide text-muted">I&apos;m curious about</p><p className="mt-1 text-sm">{p.curiousAbout}</p></div>}
        </div>
      </Card>

      {p.topics.length > 0 && (
        <Card className="p-6">
          <SectionTitle>Experience</SectionTitle>
          <ul className="space-y-3">
            {p.topics.map((t) => (
              <li key={t.topicId}>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{topicPath(t.topicId)}</span>
                  <ExperienceBadge kind={t.kind} />
                  {t.welcomesBeginners && <Badge tone="teal">Welcomes beginners</Badge>}
                </div>
                {t.detail && <p className="mt-0.5 text-sm text-ink-2">{t.detail}</p>}
              </li>
            ))}
          </ul>
          {p.verified.length > 0 && <div className="mt-4 border-t border-line pt-4"><VerifiedList p={p} /></div>}
          <p className="mt-4 text-xs text-muted">Experience is self-described unless a credential above says it was reviewed by People. Reviews apply only to that topic.</p>
        </Card>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <Card className="p-5">
          <SectionTitle>Boundaries</SectionTitle>
          <p className="text-sm">Sessions around {p.sessionLengthMinutes} minutes.</p>
          {p.cannotAdvise && <p className="mt-1 text-sm">Can&apos;t advise on: {p.cannotAdvise}</p>}
        </Card>
        <Card className="p-5">
          <SectionTitle>From completed sessions</SectionTitle>
          {p.helpedSessions === 0 ? (
            <p className="text-sm text-muted">New here — no completed sessions as a helper yet.</p>
          ) : (
            <p className="text-sm">Helped in {p.helpedSessions} session{p.helpedSessions === 1 ? "" : "s"}; {p.addressedCount} said their question was at least partly addressed.</p>
          )}
        </Card>
      </div>
    </div>
  );
}
