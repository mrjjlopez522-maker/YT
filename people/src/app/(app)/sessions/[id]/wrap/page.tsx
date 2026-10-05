import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { WrapUp } from "@/components/session/wrap";
import { Avatar, Card, PageHeader } from "@/components/ui";
import { requireViewer } from "@/lib/server/auth";
import { getService } from "@/lib/server/runtime";
import { isAppError } from "@/lib/server/service";

export const metadata = { title: "Wrap-up" };

export default async function Wrap(props: PageProps<"/sessions/[id]/wrap">) {
  const { id } = await props.params;
  const { viewer } = await requireViewer();
  const svc = getService();
  const snap = await svc.getSession(viewer, id).catch((e) => { if (isAppError(e)) notFound(); throw e; });
  if (snap.session.status === "active" || snap.session.status === "scheduled") redirect(`/sessions/${id}`);
  const takeaways = await svc.listTakeaways(viewer);
  const other = snap.other.profile;
  return (
    <div className="mx-auto max-w-2xl">
      <Link href="/sessions" className="text-sm text-muted hover:text-ink">← Sessions</Link>
      <PageHeader title="Wrapping up" />
      <Card className="mb-6 flex items-center gap-3 p-4">
        <Avatar name={other.displayName} color={other.avatarColor} size={40} />
        <div className="min-w-0">
          <p className="text-sm text-muted">With {other.displayName}</p>
          <p className="truncate font-medium">{snap.request.question}</p>
        </div>
        <Link href={`/sessions/${id}`} className="ml-auto shrink-0 text-sm text-indigo underline-offset-2 hover:underline">Messages</Link>
      </Card>
      {snap.session.status === "cancelled" ? (
        <p className="text-muted">This session was cancelled before it started.</p>
      ) : (
        <WrapUp snap={snap} savedTakeaway={takeaways.some((t) => t.sessionId === id)} />
      )}
    </div>
  );
}
