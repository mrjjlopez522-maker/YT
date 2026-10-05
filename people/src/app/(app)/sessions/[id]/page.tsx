import { notFound } from "next/navigation";
import { SessionRoom } from "@/components/session/room";
import { requireViewer } from "@/lib/server/auth";
import { getService } from "@/lib/server/runtime";
import { isAppError } from "@/lib/server/service";

export const metadata = { title: "Session" };

export default async function SessionPage(props: PageProps<"/sessions/[id]">) {
  const { id } = await props.params;
  const { viewer } = await requireViewer();
  // Non-participants get a 404 — the same as a session that doesn't exist.
  const snap = await getService().getSession(viewer, id).catch((e) => { if (isAppError(e)) notFound(); throw e; });
  return <SessionRoom snap={snap} />;
}
