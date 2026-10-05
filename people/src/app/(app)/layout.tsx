import { AppNav } from "@/components/nav";
import { requireViewer } from "@/lib/server/auth";
import { getService } from "@/lib/server/runtime";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const { viewer, profile } = await requireViewer();
  const badges = await getService().badges(viewer);
  return (
    <div className="mx-auto flex max-w-6xl">
      <AppNav
        name={profile.displayName}
        color={profile.avatarColor}
        userId={viewer.id}
        isModerator={profile.role === "moderator"}
        invites={badges.invites}
        live={badges.live}
      />
      <main id="main" className="min-w-0 flex-1 px-4 pb-28 pt-6 sm:px-6 lg:px-10 lg:pb-16 lg:pt-10">
        {children}
      </main>
    </div>
  );
}
