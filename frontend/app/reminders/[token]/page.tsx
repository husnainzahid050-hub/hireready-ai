import type { Metadata } from "next";
import { Suspense } from "react";

import { ReminderView } from "@/components/reminders/reminder-view";

// The token is in the URL: never index it, never send it as a Referer (next.config.ts adds the
// same as headers on /reminders/*).
export const metadata: Metadata = {
  title: "Your prep plan",
  robots: { index: false, follow: false, nocache: true },
  referrer: "no-referrer",
};

export default function ReminderPage() {
  return (
    <main className="mx-auto w-full max-w-xl px-4 py-10 sm:py-16">
      <Suspense fallback={<p className="text-fg-muted">Loading…</p>}>
        <ReminderView />
      </Suspense>
    </main>
  );
}
