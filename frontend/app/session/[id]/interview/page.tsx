import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { InterviewRoute } from "@/components/interview/interview-route";
import { InterviewSkeleton } from "@/components/interview/parts";

export const metadata: Metadata = {
  title: "Mock interview · HireReady AI",
  robots: { index: false },
};

// Static shell; the session-specific part (which reads the URL) streams in inside <Suspense>.
export default function InterviewPage() {
  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6 sm:py-10">
      <Link
        href="/"
        className="rounded text-sm text-zinc-600 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 dark:text-zinc-400"
      >
        ← HireReady AI
      </Link>
      <div className="mt-4">
        <Suspense fallback={<InterviewSkeleton />}>
          <InterviewRoute />
        </Suspense>
      </div>
    </main>
  );
}
