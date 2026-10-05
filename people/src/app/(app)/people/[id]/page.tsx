import { notFound, redirect } from "next/navigation";
import { PersonActions } from "@/components/person-actions";
import { ProfileView } from "@/components/profile-view";
import { requireViewer } from "@/lib/server/auth";
import { getService } from "@/lib/server/runtime";
import { isAppError } from "@/lib/server/service";

export const metadata = { title: "Profile" };

export default async function Person(props: PageProps<"/people/[id]">) {
  const { id } = await props.params;
  const { viewer } = await requireViewer();
  if (id === viewer.id) redirect("/profile");
  const p = await getService().getProfile(viewer, id).catch((e) => { if (isAppError(e)) notFound(); throw e; });
  return (
    <div className="mx-auto max-w-3xl">
      <ProfileView p={p} actions={<PersonActions userId={p.id} name={p.displayName} />} />
      <p className="mt-4 text-xs text-muted">People never shares contact details. To talk, send a request — they can accept or decline.</p>
    </div>
  );
}
