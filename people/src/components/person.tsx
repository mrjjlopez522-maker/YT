import Link from "next/link";
import { BadgeCheck } from "lucide-react";
import { languageName } from "@/lib/domain/languages";
import { getTopic } from "@/lib/domain/topics";
import type { PublicProfile } from "@/lib/server/service";
import { Avatar, Badge } from "./ui";

export function PersonLine({ p, sub }: { p: PublicProfile; sub?: React.ReactNode }) {
  return (
    <div className="flex min-w-0 items-center gap-3">
      <Avatar name={p.displayName} color={p.avatarColor} size={44} />
      <div className="min-w-0">
        <p className="flex items-center gap-2 font-semibold">
          <Link href={`/people/${p.id}`} className="truncate hover:underline">{p.displayName}</Link>
          {p.availableNow && <Badge tone="teal">Available now</Badge>}
        </p>
        <p className="truncate text-sm text-muted">
          {sub ?? [p.locationBroad, p.languages.map(languageName).join(", ")].filter(Boolean).join(" · ")}
        </p>
      </div>
    </div>
  );
}

/** Verification applies to one credential and one topic — never to the whole person. */
export function VerifiedList({ p }: { p: PublicProfile }) {
  if (!p.verified.length) return null;
  return (
    <ul className="space-y-1">
      {p.verified.map((v) => (
        <li key={v.topicId + v.title} className="flex items-start gap-1.5 text-sm text-teal">
          <BadgeCheck size={16} className="mt-0.5 shrink-0" aria-hidden />
          <span>
            <strong className="font-semibold">{v.title}</strong>
            {v.issuer && <> ({v.issuer})</>} — reviewed by People for {getTopic(v.topicId)?.name ?? v.topicId}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function ExperienceBadge({ kind }: { kind: "lived" | "professional" }) {
  return kind === "professional"
    ? <Badge tone="indigo" title="Described by the helper; not checked by People unless marked reviewed">Professional experience · self-described</Badge>
    : <Badge tone="neutral" title="Personal experience shared by the helper">Lived experience</Badge>;
}
