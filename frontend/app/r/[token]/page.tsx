import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { SharedReportView } from "@/components/report/shared-report-view";

// Generic preview only: link unfurlers (Slack, WhatsApp, LinkedIn) cache OG tags, so a score or
// name here would outlive a revoked link. Crawlers may fetch /r/* (robots.ts allows it) so they
// SEE this noindex; next.config.ts also sends X-Robots-Tag, no-referrer and no-store on /r/*.
export const metadata: Metadata = {
  title: "Shared practice report",
  description: "A read-only practice interview report made with HireReady AI.",
  robots: {
    index: false,
    follow: false,
    nocache: true,
    googleBot: { index: false, follow: false, noimageindex: true },
  },
  referrer: "no-referrer",
  openGraph: {
    title: "A HireReady practice report",
    description: "A read-only practice interview report made with HireReady AI.",
  },
  twitter: {
    title: "A HireReady practice report",
    description: "A read-only practice interview report made with HireReady AI.",
  },
};

export default function SharedReportPage() {
  return (
    <main className="report-page mx-auto w-full max-w-4xl px-4 py-6 sm:px-6 sm:py-10">
      <Link href="/" className="text-fg-muted rounded text-sm hover:underline print:hidden">
        ← HireReady AI
      </Link>
      <p className="print-only text-fg-muted text-xs">HireReady AI · shared practice report</p>
      <div className="mt-4">
        <Suspense fallback={<p className="text-fg-muted">Loading the report…</p>}>
          <SharedReportView />
        </Suspense>
      </div>
    </main>
  );
}
