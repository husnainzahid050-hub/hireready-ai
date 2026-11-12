"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ReportActions } from "@/components/report/report-actions";
import { formatDate } from "@/components/report/report-body";
import { ReportSections, type Synthesis } from "@/components/report/report-sections";
import { Badge } from "@/components/ui/badge";
import { Button, ButtonLink } from "@/components/ui/button";
import { ApiError, getReport, getToken, streamReport } from "@/lib/api";
import type { Report, ReportOverview, ReportResponse } from "@/lib/types";

const STEPS = [
  { id: "collect", label: "Score answers" },
  { id: "synthesis", label: "Hiring-manager view" },
  { id: "done", label: "Plan ready" },
];

const STREAM_ENDED = {
  code: "stream_ended",
  message: "The connection closed before the report finished. Please try again.",
};

type Err = { code: string; message: string };

function split(r: Report): { overview: ReportOverview; synthesis: Synthesis } {
  return {
    overview: {
      readiness: r.readiness,
      score_verdict: r.employer.score_verdict,
      questions: r.questions,
      speech: r.speech,
    },
    synthesis: {
      employer: r.employer,
      strengths: r.strengths,
      improvements: r.improvements,
      prep_plan: r.prep_plan,
      open_gaps: r.open_gaps,
      generated_by: r.generated_by,
    },
  };
}

function Steps({ step, done }: { step: string; done: boolean }) {
  const current = done
    ? STEPS.length
    : Math.max(
        0,
        STEPS.findIndex((s) => s.id === step),
      );
  return (
    <ol
      className="grid grid-cols-3 gap-2 text-xs sm:text-sm print:hidden"
      aria-label="Report progress"
    >
      {STEPS.map((s, i) => {
        const state = i < current ? "done" : i === current ? "active" : "todo";
        return (
          <li
            key={s.id}
            aria-current={state === "active" ? "step" : undefined}
            className={
              state === "done"
                ? "border-success-solid/40 bg-success-soft text-success-fg rounded-lg border px-3 py-2"
                : state === "active"
                  ? "border-accent/40 bg-accent-soft text-accent-soft-fg rounded-lg border px-3 py-2"
                  : "border-border text-fg-subtle rounded-lg border px-3 py-2"
            }
          >
            {state === "done" ? "✓ " : state === "active" ? "… " : ""}
            {s.label}
          </li>
        );
      })}
    </ol>
  );
}

function Notice({
  children,
  tone = "warning",
}: {
  children: React.ReactNode;
  tone?: "warning" | "danger";
}) {
  return (
    <div
      role={tone === "danger" ? "alert" : undefined}
      className={
        tone === "danger"
          ? "bg-danger-soft text-danger-fg rounded-xl p-5"
          : "bg-warning-soft text-warning-fg rounded-xl p-5"
      }
    >
      {children}
    </div>
  );
}

export function ReportView() {
  const { id: sessionId } = useParams<{ id: string }>();
  const [meta, setMeta] = useState<ReportResponse | null>(null);
  const [overview, setOverview] = useState<ReportOverview | null>(null);
  const [synthesis, setSynthesis] = useState<Synthesis | null>(null);
  const [roleTitle, setRoleTitle] = useState<string | null>(null);
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);
  const [step, setStep] = useState("collect");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<Err | null>(null);
  const [blocked, setBlocked] = useState<"no_token" | "not_completed" | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    // Each run owns its AbortController; React Strict Mode's extra dev mount aborts the first
    // run during its initial GET, before any report build starts.
    const controller = new AbortController();

    const show = (r: Report) => {
      const parts = split(r);
      setOverview(parts.overview);
      setSynthesis(parts.synthesis);
      setRoleTitle(r.role_title);
      setGeneratedAt(r.generated_at);
      setStep("done");
    };

    (async () => {
      if (!getToken(sessionId)) return setBlocked("no_token");
      try {
        const saved = await getReport(sessionId);
        if (controller.signal.aborted) return;
        setMeta(saved);
        if (saved.report) return show(saved.report);
        let finished = false;
        for await (const ev of streamReport(sessionId, controller.signal)) {
          if (ev.event === "status") {
            if (STEPS.some((s) => s.id === ev.data.step)) setStep(ev.data.step);
            setMessage(ev.data.message);
          } else if (ev.event === "overview") {
            setOverview(ev.data);
            setStep("synthesis");
          } else if (ev.event === "done") {
            finished = true;
            show(ev.data);
          } else if (ev.event === "error") {
            finished = true;
            if (ev.data.code === "session_not_found") return setBlocked("no_token");
            setError(ev.data);
          }
        }
        if (!finished && !controller.signal.aborted) setError(STREAM_ENDED);
        // Refresh share / email state now that the report row exists.
        if (finished && !controller.signal.aborted) setMeta(await getReport(sessionId));
      } catch (e) {
        if (controller.signal.aborted) return;
        if (e instanceof ApiError && e.code === "session_not_found") return setBlocked("no_token");
        if (e instanceof ApiError && e.code === "interview_not_completed")
          return setBlocked("not_completed");
        setError({
          code: e instanceof ApiError ? e.code : "network",
          message: e instanceof ApiError ? e.message : "Connection lost. Please try again.",
        });
      }
    })();
    return () => controller.abort();
  }, [sessionId, attempt]);

  if (blocked === "no_token")
    return (
      <Notice>
        This report belongs to another browser, or it was deleted or has expired. For privacy,
        sessions open only on the device that created them.{" "}
        <Link href="/start" className="font-medium underline">
          Start a new one
        </Link>
        .
      </Notice>
    );
  if (blocked === "not_completed")
    return (
      <Notice>
        Finish the mock interview first; the report is built from your answers.{" "}
        <Link href={`/session/${sessionId}/interview`} className="font-medium underline">
          Back to the interview
        </Link>
        .
      </Notice>
    );

  const done = synthesis !== null;
  const date = formatDate(generatedAt);

  return (
    <div className="space-y-6">
      <header className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-3xl font-semibold tracking-tight text-balance">
            {roleTitle ? `Interview report: ${roleTitle}` : "Your interview report"}
          </h1>
          {meta?.is_demo && <Badge>Sample CV</Badge>}
        </div>
        {date && <p className="text-fg-muted text-sm">Practice interview · {date}</p>}
        {!done && !error && (
          <>
            <p className="text-fg-muted" aria-live="polite">
              {message ?? "Starting…"}
            </p>
            <Steps step={step} done={false} />
          </>
        )}
        {done && meta && <ReportActions sessionId={sessionId} meta={meta} onMeta={setMeta} />}
      </header>

      {error && (
        <Notice tone="danger">
          <p className="font-medium">{error.message}</p>
          <Button
            variant="secondary"
            size="sm"
            className="mt-3"
            onClick={() => {
              setError(null);
              setAttempt((a) => a + 1);
            }}
          >
            Try again
          </Button>
        </Notice>
      )}

      {overview ? (
        <ReportSections
          overview={overview}
          synthesis={synthesis}
          failed={!!error}
          expiresAt={meta?.expires_at ?? null}
          planFooter={
            <ButtonLink href="/start" size="sm" className="mt-2 print:hidden">
              Practice again
            </ButtonLink>
          }
        />
      ) : (
        !error && (
          <div
            className="bg-surface-sunken h-48 animate-pulse rounded-2xl motion-reduce:animate-none"
            aria-hidden
          />
        )
      )}
    </div>
  );
}
