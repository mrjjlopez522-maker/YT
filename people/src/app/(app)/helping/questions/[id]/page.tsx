import Link from "next/link";
import { notFound } from "next/navigation";
import { AsyncAnswerForm } from "@/components/helping";
import { Badge, Card, Notice } from "@/components/ui";
import { intentLabel, RESPECT_NOTE } from "@/lib/domain/prompts";
import { isPerspective, topicPath } from "@/lib/domain/topics";
import { requireViewer } from "@/lib/server/auth";
import { getService } from "@/lib/server/runtime";
import { isAppError } from "@/lib/server/service";

export default async function AsyncQuestion(props: PageProps<"/helping/questions/[id]">) {
  const { id } = await props.params;
  const { viewer } = await requireViewer();
  const q = await getService().getAsyncQuestion(viewer, id).catch((e) => { if (isAppError(e)) notFound(); throw e; });
  return (
    <div className="mx-auto max-w-2xl">
      <Link href="/helping" className="text-sm text-muted hover:text-ink">← Helping</Link>
      <Card className="mt-3 p-6">
        <div className="flex flex-wrap gap-2"><Badge tone="indigo">{intentLabel(q.request.intent)}</Badge><Badge>{topicPath(q.request.topicId)}</Badge></div>
        <h1 className="mt-3 font-display text-2xl font-semibold leading-snug">{q.request.question}</h1>
        {q.request.context && <p className="prewrap mt-3 text-sm text-ink-2">{q.request.context}</p>}
      </Card>
      {isPerspective(q.request.topicId) && <Notice tone="indigo" className="mt-4">{RESPECT_NOTE}</Notice>}
      {q.myResponses.length > 0 && (
        <div className="mt-6 space-y-2">
          <p className="text-sm font-medium">Your earlier replies</p>
          {q.myResponses.map((r) => <Card key={r.id} className="prewrap p-4 text-sm">{r.body}</Card>)}
        </div>
      )}
      <div className="mt-6"><AsyncAnswerForm requestId={q.request.id} /></div>
    </div>
  );
}
