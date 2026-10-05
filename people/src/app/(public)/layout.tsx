import Link from "next/link";
import { Logo } from "@/components/nav";

export default function PublicLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-3xl px-4 pb-16 pt-6 sm:px-6">
      <header className="mb-8 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2">
          <Logo />
          <span className="font-display text-xl font-semibold tracking-tight">People</span>
        </Link>
        <nav className="flex gap-4 text-sm text-muted">
          <Link href="/safety" className="hover:text-ink">Safety</Link>
          <Link href="/setup" className="hover:text-ink">Setup</Link>
        </nav>
      </header>
      <main id="main">{children}</main>
    </div>
  );
}
