import type { Metadata } from "next";

import { DemoButton } from "@/components/demo-button";
import { StartForm } from "@/components/start-form";
import { Container } from "@/components/ui/section";

export const metadata: Metadata = {
  title: "Start your mock interview",
  description:
    "Upload your CV and paste a job description to get skill gaps with evidence, likely questions and a 7-day plan.",
  alternates: { canonical: "/start" },
};

export default function StartPage() {
  return (
    <main className="py-10 sm:py-14">
      <Container size="narrow" className="space-y-10">
        <header className="space-y-3">
          <p className="text-link text-sm font-semibold tracking-wide uppercase">New session</p>
          <h1 className="text-3xl font-semibold tracking-tight text-balance sm:text-4xl">
            Set up your mock interview
          </h1>
          <p className="text-fg-muted max-w-2xl sm:text-lg">
            Upload your CV and paste the job you&apos;re applying for. You&apos;ll get your skill
            gaps with evidence, likely questions and a 7-day plan, then the interview itself.
          </p>
        </header>

        <div className="border-border bg-surface-muted flex flex-col gap-4 rounded-2xl border p-5 sm:flex-row sm:items-center sm:justify-between">
          <div className="space-y-1">
            <p className="font-medium">Just exploring?</p>
            <p className="text-fg-muted text-sm">
              Skip the upload and see the full flow with a fictional sample CV.
            </p>
          </div>
          <DemoButton size="md" />
        </div>

        <StartForm />
      </Container>
    </main>
  );
}
