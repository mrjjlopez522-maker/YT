import { signOut } from "@/app/actions";
import { Notice } from "@/components/ui";

export default function Suspended() {
  return (
    <div className="space-y-4">
      <h1 className="font-display text-3xl font-semibold">Your account is suspended</h1>
      <Notice tone="rose">A moderator suspended this account, so you can&apos;t send or accept requests. If you think this is a mistake, contact the pilot team.</Notice>
      <form action={signOut}><button className="text-sm underline">Sign out</button></form>
    </div>
  );
}
