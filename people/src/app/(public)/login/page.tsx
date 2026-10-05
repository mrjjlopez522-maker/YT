import { redirect } from "next/navigation";
import { DemoPersonas, EmailLogin } from "@/components/login";
import { Card, Notice } from "@/components/ui";
import { serverConfig } from "@/lib/config";
import { DEMO_PERSONAS, buildDemoData } from "@/lib/demo/fixtures";
import { currentViewer } from "@/lib/server/auth";

export const metadata = { title: "Sign in" };

export default async function Login(props: PageProps<"/login">) {
  const sp = await props.searchParams;
  if (await currentViewer()) redirect("/");
  const demo = serverConfig().mode === "demo";
  const profiles = buildDemoData().profiles;
  const personas = DEMO_PERSONAS.map((p) => {
    const prof = profiles.find((x) => x.id === p.id)!;
    return { ...p, name: prof.displayName, color: prof.avatarColor };
  });
  return (
    <div className="animate-rise">
      <h1 className="font-display text-4xl font-semibold leading-tight tracking-tight sm:text-5xl">Someone knows.<br />Meet them.</h1>
      <p className="mt-3 max-w-lg text-lg text-ink-2">Tell us what you need. Find someone who can help — by text, voice or video.</p>
      {sp.error && <Notice tone="rose" className="mt-6">That sign-in link didn&apos;t work. Please request a new one.</Notice>}
      {demo ? (
        <section className="mt-8">
          <Notice tone="amber" title="You're looking at the demo">
            There are no real accounts here. Pick a sample person to explore. To try both sides of a request, open a
            private window and sign in as someone else (for example Maya asks, Omar helps).
          </Notice>
          <div className="mt-6"><DemoPersonas personas={personas} /></div>
        </section>
      ) : (
        <Card className="mt-8 max-w-md p-6">
          <p className="mb-4 text-sm text-muted">The pilot is for invited adults. Sign in with the email you were invited with.</p>
          <EmailLogin />
        </Card>
      )}
    </div>
  );
}
