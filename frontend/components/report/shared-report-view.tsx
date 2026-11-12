"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { DemoButton } from "@/components/demo-button";
import { PrintExpander } from "@/components/report/report-actions";
import { formatDate } from "@/components/report/report-body";
import { ReportSections } from "@/components/report/report-sections";
import { Card } from "@/components/ui/card";
import { ApiError, getSharedReport } from "@/lib/api";
import type { SharedReportResponse } from "@/lib/types";

/** Read-only report behind a share token: no actions, no delete, a CTA for visitors. */
export function SharedReportView() {
  const { token } = useParams<{ token: string }>();
  const [data, setData] = useState<SharedReportResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getSharedReport(token)
      .then((d) => alive && setData(d))
      .catch((e: unknown) => {
        if (!alive) return;
        setError(
          e instanceof ApiError && e.status === 404
            ? e.message
            : "We couldn't load this report. Please try again in a moment.",
        );
      });
    return () => {
      alive = false;
    };
  }, [token]);

  const cta = (
    <Card tone="muted" className="flex flex-col items-start gap-3 print:hidden">
      <p className="font-medium">Practise for your own interview</p>
      <p className="text-fg-muted text-sm">
        HireReady analyses your CV against a real job, runs a mock interview with follow-ups and
        scores every answer with quotes. Try it in 30 seconds with a sample CV.
      </p>
      <DemoButton size="md" variant="primary" />
    </Card>
  );

  if (error)
    return (
      <div className="space-y-6">
        <div role="alert" className="bg-warning-soft text-warning-fg rounded-xl p-5">
          {error}
        </div>
        {cta}
      </div>
    );
  if (!data)
    return (
      <div
        className="bg-surface-sunken h-48 animate-pulse rounded-2xl motion-reduce:animate-none"
        aria-hidden
      />
    );

  const r = data.report;
  const expires = formatDate(data.expires_at);
  return (
    <div className="space-y-6">
      <PrintExpander />
      <p className="bg-accent-soft text-accent-soft-fg rounded-xl px-4 py-3 text-sm">
        <strong>Shared practice report · read-only.</strong> Made with a mock interview on HireReady
        AI{expires ? `; this link stops working on ${expires}` : ""}.
      </p>
      <header className="space-y-1">
        <h1 className="text-3xl font-semibold tracking-tight text-balance">
          {r.role_title ? `Interview report: ${r.role_title}` : "Interview report"}
        </h1>
        {formatDate(r.generated_at) && (
          <p className="text-fg-muted text-sm">Practice interview · {formatDate(r.generated_at)}</p>
        )}
      </header>
      <ReportSections
        overview={{
          readiness: r.readiness,
          score_verdict: r.employer.score_verdict,
          questions: r.questions,
          speech: r.speech,
        }}
        synthesis={r}
        failed={false}
        expiresAt={data.expires_at}
      />
      {cta}
    </div>
  );
}
