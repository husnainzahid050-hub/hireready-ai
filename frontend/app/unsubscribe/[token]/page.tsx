import type { Metadata } from "next";
import { Suspense } from "react";

import { UnsubscribeView } from "@/components/reminders/unsubscribe-view";

export const metadata: Metadata = {
  title: "Unsubscribe",
  robots: { index: false, follow: false, nocache: true },
  referrer: "no-referrer",
};

export default function UnsubscribePage() {
  return (
    <main className="mx-auto w-full max-w-xl px-4 py-10 sm:py-16">
      <Suspense fallback={<p className="text-fg-muted">Loading…</p>}>
        <UnsubscribeView />
      </Suspense>
    </main>
  );
}
