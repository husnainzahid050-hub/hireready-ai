import type { Metadata } from "next";
import { Suspense } from "react";

import { InterviewRoute } from "@/components/interview/interview-route";
import { InterviewSkeleton } from "@/components/interview/parts";

export const metadata: Metadata = {
  title: "Mock interview",
  robots: { index: false },
};

// Static shell; the session-specific part (which reads the URL) streams in inside <Suspense>.
// `data-focus-mode` hides the site footer (rule in globals.css) so the interview stays focused.
export default function InterviewPage() {
  return (
    <main data-focus-mode className="mx-auto w-full max-w-5xl px-5 py-6 sm:px-6 sm:py-10">
      <Suspense fallback={<InterviewSkeleton />}>
        <InterviewRoute />
      </Suspense>
    </main>
  );
}
