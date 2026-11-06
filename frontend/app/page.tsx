import Link from "next/link";

import { DemoButton } from "@/components/demo-button";

// Minimal landing for now; the full landing page is built in Phase 6.
export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center gap-8 px-6 py-16">
      <div className="space-y-4">
        <p className="text-sm font-semibold tracking-wide text-indigo-600 uppercase dark:text-indigo-400">
          HireReady AI
        </p>
        <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">
          Paste the job. Upload your CV. Walk into the interview ready.
        </h1>
        <p className="text-lg text-zinc-600 dark:text-zinc-400">
          See exactly which required skills your CV proves (with quotes), what this role will ask
          you, and a 7-day plan to close the gaps.
        </p>
      </div>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
        <Link
          href="/start"
          className="rounded-lg bg-indigo-600 px-5 py-3 text-center font-medium text-white transition-colors hover:bg-indigo-700 focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 focus-visible:outline-none"
        >
          Start free mock interview
        </Link>
        <DemoButton />
      </div>
      <p className="text-sm text-zinc-500">
        Audio is never stored. Guest data auto-deletes in 7 days.
      </p>
    </main>
  );
}
