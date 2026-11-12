import type { Metadata } from "next";

import { ButtonLink } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

export const metadata: Metadata = {
  title: "Data deleted",
  robots: { index: false, follow: false },
};

export default function DeletedPage() {
  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-16 sm:px-6">
      <Card className="space-y-3">
        <h1 className="text-2xl font-semibold tracking-tight">Deleted.</h1>
        <p className="text-fg-muted">
          Your CV text, job description, answers, transcripts, report and reminders are gone from
          our database, and any share link no longer works. Audio was never stored.
        </p>
        <ButtonLink href="/start" className="mt-2">
          Start a new session
        </ButtonLink>
      </Card>
    </main>
  );
}
