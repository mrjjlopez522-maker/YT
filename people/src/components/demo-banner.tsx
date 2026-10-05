import Link from "next/link";

export function DemoBanner() {
  return (
    <div className="border-b border-amber-ink/20 bg-amber-soft text-amber-ink">
      <p className="mx-auto max-w-6xl px-4 py-2 text-center text-[13px] leading-snug">
        <strong className="font-semibold">Demo mode.</strong> Sample people and local data only — nobody real is on the other
        side, and calls are not connected.{" "}
        <Link href="/setup" className="underline underline-offset-2">What needs configuring?</Link>
      </p>
    </div>
  );
}
