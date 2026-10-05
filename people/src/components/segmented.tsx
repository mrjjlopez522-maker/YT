import Link from "next/link";
import { cx } from "./ui";

export function RequestsTabs({ active, invites }: { active: "mine" | "helping"; invites: number }) {
  const tab = (href: string, on: boolean, label: React.ReactNode) => (
    <Link href={href} aria-current={on ? "page" : undefined}
      className={cx("flex-1 rounded-lg px-3 py-2 text-center text-sm font-medium transition-colors", on ? "bg-card text-ink shadow-sm" : "text-muted hover:text-ink")}>
      {label}
    </Link>
  );
  return (
    <nav aria-label="Requests" className="mb-6 flex rounded-xl bg-paper-2 p-1 lg:hidden">
      {tab("/requests", active === "mine", "My requests")}
      {tab("/helping", active === "helping", <>Helping{invites > 0 && <span className="ml-1.5 rounded-full bg-indigo px-1.5 text-xs text-white">{invites}</span>}</>)}
    </nav>
  );
}
