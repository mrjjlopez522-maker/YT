"use client";

export default function Error({ reset }: { error: Error; reset: () => void }) {
  return (
    <main id="main" className="mx-auto max-w-md px-6 py-24 text-center">
      <h1 className="font-display text-3xl font-semibold">Something went wrong</h1>
      <p className="mt-2 text-muted">It&apos;s on our side. Your data is safe — try again in a moment.</p>
      <button onClick={reset} className="mt-6 rounded-xl bg-indigo px-4 py-2 text-white">Try again</button>
    </main>
  );
}
