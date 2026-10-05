import Link from "next/link";
import { AvailabilityEditor, CredentialForm, HelperTopicsEditor, ProfileForm } from "@/components/profile-form";
import { Card, PageHeader } from "@/components/ui";
import { requireViewer } from "@/lib/server/auth";
import { getService } from "@/lib/server/runtime";

export const metadata = { title: "Edit profile" };

export default async function EditProfile() {
  const { viewer, profile } = await requireViewer();
  const setup = await getService().myHelperSetup(viewer);
  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <Link href="/profile" className="text-sm text-muted hover:text-ink">← Profile</Link>
      <PageHeader title="Edit profile" subtitle="Everyone can both learn and help." />
      <Card className="p-6"><ProfileForm profile={profile} /></Card>
      <section id="helping" className="scroll-mt-6">
        <h2 className="mb-3 font-display text-2xl font-semibold">Topics you can help with</h2>
        <Card className="p-6"><HelperTopicsEditor initial={setup.topics} /></Card>
      </section>
      <section>
        <h2 className="mb-3 font-display text-2xl font-semibold">Usual availability</h2>
        <Card className="p-6"><AvailabilityEditor initial={setup.windows} timezone={profile.timezone} /></Card>
      </section>
      <section id="credentials" className="scroll-mt-6">
        <h2 className="mb-1 font-display text-2xl font-semibold">Ask for a credential review</h2>
        <p className="mb-3 text-sm text-muted">Optional. You can&apos;t mark yourself as verified; a moderator reviews each credential for one topic.</p>
        <Card className="p-6"><CredentialForm /></Card>
      </section>
    </div>
  );
}
