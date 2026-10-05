import { redirect } from "next/navigation";
import { ProfileForm } from "@/components/profile-form";
import { Card } from "@/components/ui";
import { currentUserId } from "@/lib/server/auth";
import { getService } from "@/lib/server/runtime";

export const metadata = { title: "Welcome" };

export default async function Onboarding() {
  const id = await currentUserId();
  if (!id) redirect("/login");
  const found = await getService().viewerFor(id);
  if (found?.profile.onboarded) redirect("/");
  return (
    <div>
      <h1 className="font-display text-4xl font-semibold tracking-tight">Welcome to People</h1>
      <p className="mt-2 text-ink-2">Everyone here can both learn and help. Tell people a little about you — you can add topics you help with afterwards.</p>
      <Card className="mt-6 p-6"><ProfileForm profile={found?.profile ?? null} onboarding /></Card>
    </div>
  );
}
