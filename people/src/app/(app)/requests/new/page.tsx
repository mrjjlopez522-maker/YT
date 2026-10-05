import { RequestWizard } from "@/components/requests/wizard";
import { getTopic } from "@/lib/domain/topics";
import type { Intent } from "@/lib/domain/types";
import { requireViewer } from "@/lib/server/auth";

export const metadata = { title: "New request" };

export default async function NewRequest(props: PageProps<"/requests/new">) {
  const sp = await props.searchParams;
  const { profile } = await requireViewer();
  const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? "";
  const intent = (["ask", "learn", "move", "explore"].includes(one(sp.intent)) ? one(sp.intent) : "") as Intent | "";
  const topic = getTopic(one(sp.topic)) ? one(sp.topic) : "";
  return (
    <RequestWizard
      initialQuestion={one(sp.q).slice(0, 600)}
      initialIntent={intent}
      initialTopic={topic}
      surprise={one(sp.surprise) === "1"}
      noneAvailable={one(sp.none) === "1"}
      languages={profile.languages}
      formats={profile.formats}
    />
  );
}
