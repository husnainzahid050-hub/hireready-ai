import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { AnalysisRoute } from "@/components/analysis-route";

export const metadata: Metadata = {
  title: "Your analysis · HireReady AI",
  robots: { index: false },
};

// Static shell; the session-specific part (which reads the URL) streams in inside <Suspense>.
export default function AnalysisPage() {
  return (
    <main className="mx-auto w-full max-w-4xl px-6 py-10">
      <Link href="/" className="text-sm text-zinc-500 hover:underline">
        ← HireReady AI
      </Link>
      <div className="mt-4">
        <Suspense fallback={<p className="text-zinc-500">Loading your analysis…</p>}>
          <AnalysisRoute />
        </Suspense>
      </div>
    </main>
  );
}
