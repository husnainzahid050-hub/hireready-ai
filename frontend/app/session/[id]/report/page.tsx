import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { ReportView } from "@/components/report/report-view";

export const metadata: Metadata = {
  title: "Your interview report",
  robots: { index: false, follow: false },
};

// Static shell; the session-specific part (which reads the URL) streams in inside <Suspense>.
export default function ReportPage() {
  return (
    <main className="report-page mx-auto w-full max-w-4xl px-4 py-6 sm:px-6 sm:py-10">
      <Link href="/" className="text-fg-muted rounded text-sm hover:underline print:hidden">
        ← HireReady AI
      </Link>
      <p className="print-only text-fg-muted text-xs">HireReady AI · practice interview report</p>
      <div className="mt-4">
        <Suspense fallback={<p className="text-fg-muted">Loading your report…</p>}>
          <ReportView />
        </Suspense>
      </div>
    </main>
  );
}
