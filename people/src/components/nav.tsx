"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BookOpen, Home, Inbox, MessagesSquare, Settings2, ShieldCheck, User, HandHeart } from "lucide-react";
import { signOut } from "@/app/actions";
import { Avatar, cx } from "./ui";
import { LiveRefresher } from "./live";

type Item = { href: string; label: string; icon: typeof Home; match: (p: string) => boolean; badge?: number };

export function AppNav({
  name, color, userId, isModerator, invites, live,
}: { name: string; color: string; userId: string; isModerator: boolean; invites: number; live: number }) {
  const path = usePathname();
  const side: Item[] = [
    { href: "/", label: "Home", icon: Home, match: (p) => p === "/" },
    { href: "/requests", label: "My requests", icon: Inbox, match: (p) => p.startsWith("/requests") },
    { href: "/helping", label: "Helping", icon: HandHeart, match: (p) => p.startsWith("/helping"), badge: invites },
    { href: "/sessions", label: "Sessions", icon: MessagesSquare, match: (p) => p.startsWith("/sessions"), badge: live },
    { href: "/learning", label: "My learning", icon: BookOpen, match: (p) => p.startsWith("/learning") },
    { href: "/profile", label: "Profile", icon: User, match: (p) => p.startsWith("/profile") || p.startsWith("/people") },
    ...(isModerator ? [{ href: "/moderation", label: "Moderation", icon: ShieldCheck, match: (p: string) => p.startsWith("/moderation") }] : []),
  ];
  const bottom: Item[] = [
    side[0],
    { ...side[1], label: "Requests", match: (p) => p.startsWith("/requests") || p.startsWith("/helping"), badge: invites },
    side[3],
    { ...side[5], match: (p) => p.startsWith("/profile") || p.startsWith("/people") || p.startsWith("/learning") || p.startsWith("/moderation") },
  ];

  return (
    <>
      <LiveRefresher topics={[`user:${userId}`]} />
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r border-line px-3 py-5 lg:flex">
        <Link href="/" className="mb-6 flex items-center gap-2 px-3">
          <Logo />
          <span className="font-display text-xl font-semibold tracking-tight">People</span>
        </Link>
        <nav aria-label="Main" className="flex flex-1 flex-col gap-0.5">
          {side.map((it) => <SideLink key={it.href} item={it} active={it.match(path)} />)}
        </nav>
        <div className="mt-4 border-t border-line pt-4">
          <Link href="/setup" className="flex items-center gap-3 rounded-xl px-3 py-2 text-sm text-muted hover:bg-paper-2">
            <Settings2 size={16} aria-hidden /> Setup &amp; status
          </Link>
          <div className="mt-2 flex items-center gap-3 px-3 py-2">
            <Avatar name={name} color={color} size={30} />
            <span className="min-w-0 flex-1 truncate text-sm font-medium">{name}</span>
          </div>
          <form action={signOut} className="px-3">
            <button className="text-sm text-muted underline-offset-2 hover:underline">Sign out</button>
          </form>
        </div>
      </aside>

      <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-paper/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden">
        <ul className="mx-auto grid max-w-md grid-cols-4">
          {bottom.map((it) => {
            const active = it.match(path);
            const Icon = it.icon;
            return (
              <li key={it.href}>
                <Link
                  href={it.href}
                  aria-current={active ? "page" : undefined}
                  className={cx("relative flex flex-col items-center gap-0.5 py-2.5 text-[11px] font-medium", active ? "text-indigo" : "text-muted")}
                >
                  <Icon size={22} aria-hidden strokeWidth={active ? 2.3 : 1.8} />
                  {it.label}
                  {!!it.badge && (
                    <span className="absolute right-[calc(50%-20px)] top-1.5 min-w-4 rounded-full bg-indigo px-1 text-center text-[10px] leading-4 text-white">
                      {it.badge}<span className="sr-only"> new</span>
                    </span>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </>
  );
}

function SideLink({ item, active }: { item: Item; active: boolean }) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={cx(
        "flex items-center gap-3 rounded-xl px-3 py-2.5 text-[15px] transition-colors",
        active ? "bg-indigo-soft font-semibold text-indigo-ink" : "text-ink-2 hover:bg-paper-2",
      )}
    >
      <Icon size={18} aria-hidden />
      <span className="flex-1">{item.label}</span>
      {!!item.badge && <span className="rounded-full bg-indigo px-1.5 text-xs leading-5 text-white">{item.badge}<span className="sr-only"> new</span></span>}
    </Link>
  );
}

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden>
      <rect width="64" height="64" rx="16" fill="#4338ca" />
      <circle cx="24" cy="28" r="9" fill="#faf7f2" />
      <circle cx="41" cy="36" r="9" fill="#5eead4" />
    </svg>
  );
}
