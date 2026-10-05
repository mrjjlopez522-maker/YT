import Link from "next/link";

export default function NotFound() {
  return (
    <main id="main" className="mx-auto max-w-md px-6 py-24 text-center">
      <h1 className="font-display text-3xl font-semibold">Nothing here</h1>
      <p className="mt-2 text-muted">This page doesn&apos;t exist, or it&apos;s private to other people.</p>
      <Link href="/" className="mt-6 inline-block text-indigo underline">Go home</Link>
    </main>
  );
}
