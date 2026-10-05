import Link from "next/link";
import { BookOpen, Settings2, ShieldCheck } from "lucide-react";
import { signOut } from "@/app/actions";
import { LocalTime } from "@/components/local-time";
import { UnblockButton } from "@/components/person-actions";
import { ProfileView } from "@/components/profile-view";
import { Badge, Card, LinkButton, SectionTitle } from "@/components/ui";
import { getTopic } from "@/lib/domain/topics";
import { requireViewer } from "@/lib/server/auth";
import { getService } from "@/lib/server/runtime";

export const metadata = { title: "Profile" };

const CRED_TONE = { pending: "amber", verified: "teal", rejected: "rose", revoked: "rose" } as const;

export default async function MyProfile() {
  const { viewer, profile } = await requireViewer();
  const svc = getService();
  const [p, creds, feedback, blocks] = await Promise.all([svc.getProfile(viewer, viewer.id), svc.myCredentials(viewer), svc.myFeedback(viewer), svc.listBlocks(viewer)]);
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <nav className="grid grid-cols-3 gap-2 lg:hidden" aria-label="More">
        <Link href="/learning" className="flex flex-col items-center gap-1 rounded-2xl border border-line bg-card p-3 text-sm"><BookOpen size={18} aria-hidden /> My learning</Link>
        <Link href="/setup" className="flex flex-col items-center gap-1 rounded-2xl border border-line bg-card p-3 text-sm"><Settings2 size={18} aria-hidden /> Setup</Link>
        {profile.role === "moderator" ? (
          <Link href="/moderation" className="flex flex-col items-center gap-1 rounded-2xl border border-line bg-card p-3 text-sm"><ShieldCheck size={18} aria-hidden /> Moderation</Link>
        ) : (
          <Link href="/safety" className="flex flex-col items-center gap-1 rounded-2xl border border-line bg-card p-3 text-sm"><ShieldCheck size={18} aria-hidden /> Safety</Link>
        )}
      </nav>
      <ProfileView p={p} actions={<LinkButton href="/profile/edit" variant="secondary" size="sm">Edit profile</LinkButton>} />

      <Card className="p-6">
        <SectionTitle aside={<Link href="/profile/edit#credentials" className="text-sm text-indigo hover:underline">Submit one</Link>}>Credential reviews</SectionTitle>
        {creds.length === 0 ? <p className="text-sm text-muted">None submitted. You never need one to help — lived experience is welcome.</p> : (
          <ul className="space-y-2">
            {creds.map((c) => (
              <li key={c.id} className="flex flex-wrap items-center gap-2 text-sm">
                <Badge tone={CRED_TONE[c.status]}>{c.status}</Badge>
                <span className="font-medium">{c.title}</span>
                <span className="text-muted">· {getTopic(c.topicId)?.name}</span>
                {c.reviewerNote && c.status !== "pending" && <span className="w-full text-xs text-muted">Moderator note: {c.reviewerNote}</span>}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card className="p-6">
        <SectionTitle>Notes people left you <span className="normal-case">(private)</span></SectionTitle>
        {feedback.filter((f) => f.comment).length === 0 ? <p className="text-sm text-muted">No notes yet.</p> : (
          <ul className="space-y-3">
            {feedback.filter((f) => f.comment).map((f) => (
              <li key={f.id} className="text-sm"><p className="prewrap">“{f.comment}”</p><p className="text-xs text-muted"><LocalTime iso={f.createdAt} mode="date" /></p></li>
            ))}
          </ul>
        )}
      </Card>

      <Card className="p-6">
        <SectionTitle>Blocked</SectionTitle>
        {blocks.length === 0 ? <p className="text-sm text-muted">You haven&apos;t blocked anyone.</p> : (
          <ul className="space-y-1">
            {blocks.map((b) => <li key={b.blockedId} className="flex items-center justify-between text-sm">{b.displayName}<UnblockButton userId={b.blockedId} /></li>)}
          </ul>
        )}
      </Card>

      <form action={signOut} className="lg:hidden"><button className="text-sm text-muted underline">Sign out</button></form>
    </div>
  );
}
