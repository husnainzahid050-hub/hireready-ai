import type { Metadata } from "next";
import { Suspense } from "react";

import { AnalysisRoute } from "@/components/analysis-route";

export const metadata: Metadata = {
  title: "Your analysis",
  robots: { index: false },
};

// Static shell; the session-specific part (which reads the URL) streams in inside <Suspense>.
// The site header already links home, so there is no separate back link here.
export default function AnalysisPage() {
  return (
    <main className="mx-auto w-full max-w-4xl px-5 py-8 sm:px-6 sm:py-10">
      <Suspense fallback={<p className="text-fg-muted">Loading your analysis…</p>}>
        <AnalysisRoute />
      </Suspense>
    </main>
  );
}
