"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Button, ButtonLink } from "@/components/ui/button";
import { Card as UiCard } from "@/components/ui/card";
import { cn, focusRing } from "@/components/ui/cn";
import { Alert, ArrowRight, Check, ChevronDown, ExternalLink } from "@/components/ui/icons";
import { Notice } from "@/components/ui/notice";
import { ApiError, getAnalysis, getToken, streamAnalysis } from "@/lib/api";
import type {
  GapItem,
  PrepDay,
  Profiles,
  QuestionGroup,
  ScoreBreakdown,
  Strength,
  Verdict,
} from "@/lib/types";

const STEPS = [
  { id: "extract", label: "Read CV & job" },
  { id: "index", label: "Index CV" },
  { id: "match", label: "Match skills" },
  { id: "insights", label: "Questions & plan" },
];
const STEP_IDS = new Set(STEPS.map((s) => s.id));

const STREAM_ENDED = {
  code: "stream_ended",
  message: "The connection closed before the analysis finished. Please try again.",
};

type State = {
  step: string | null;
  message: string | null;
  profiles: Profiles | null;
  score: { match_score: number; breakdown: ScoreBreakdown } | null;
  gaps: GapItem[] | null;
  strengths: Strength[] | null;
  questions: QuestionGroup[] | null;
  plan: PrepDay[] | null;
  roleTitle: string | null;
  done: boolean;
  /** Loaded from the saved analysis instead of a fresh stream. */
  restored: boolean;
  error: { code: string; message: string } | null;
};

const INITIAL: State = {
  step: null,
  message: null,
  profiles: null,
  score: null,
  gaps: null,
  strengths: null,
  questions: null,
  plan: null,
  roleTitle: null,
  done: false,
  restored: false,
  error: null,
};

// ------------------------------------------------------------------ small pieces

function Section({
  id,
  title,
  aside,
  children,
}: {
  id: string;
  title: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <UiCard as="section" aria-labelledby={`${id}-heading`} id={id} className="scroll-mt-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 id={`${id}-heading`} className="text-lg font-semibold tracking-tight">
          {title}
        </h2>
        {aside}
      </div>
      {children}
    </UiCard>
  );
}

/** Loading placeholder while streaming; a static "not available" line once the run stopped. */
function Pending({ lines = 3, stopped }: { lines?: number; stopped: boolean }) {
  if (stopped) {
    return (
      <p className="text-fg-subtle text-sm">
        Not available: the analysis stopped before this part finished. Use &ldquo;Try again&rdquo;
        above.
      </p>
    );
  }
  return (
    <div className="space-y-3" aria-hidden>
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="bg-surface-sunken h-4 animate-pulse rounded motion-reduce:animate-none"
          style={{ width: `${90 - i * 12}%` }}
        />
      ))}
    </div>
  );
}

function Progress({
  step,
  done,
  stopped,
}: {
  step: string | null;
  done: boolean;
  /** The run ended with an error: the step it was on is marked stopped, nothing pulses. */
  stopped: boolean;
}) {
  const current = done
    ? STEPS.length
    : Math.max(
        0,
        STEPS.findIndex((s) => s.id === step),
      );
  return (
    <ol className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4" aria-label="Analysis progress">
      {STEPS.map((s, i) => {
        const state =
          i < current ? "done" : i === current && !done ? (stopped ? "stopped" : "active") : "todo";
        return (
          <li
            key={s.id}
            aria-current={state === "active" || state === "stopped" ? "step" : undefined}
            className={cn(
              "flex items-center gap-2 rounded-lg border px-3 py-2",
              state === "done" && "border-success-solid/30 bg-success-soft text-success-fg",
              state === "active" && "border-accent/40 bg-accent-soft text-accent-soft-fg",
              state === "stopped" && "border-warning-solid/40 bg-warning-soft text-warning-fg",
              state === "todo" && "border-border text-fg-subtle",
            )}
          >
            {state === "done" ? (
              <Check className="size-4 shrink-0" />
            ) : state === "active" ? (
              <span
                aria-hidden
                className="bg-accent size-2 shrink-0 animate-pulse rounded-full motion-reduce:animate-none"
              />
            ) : state === "stopped" ? (
              <Alert className="size-4 shrink-0" />
            ) : (
              <span aria-hidden className="bg-border-strong size-2 shrink-0 rounded-full" />
            )}
            <span>
              {s.label}
              {state === "done" && <span className="sr-only"> (done)</span>}
              {state === "stopped" && <span className="sr-only"> (stopped)</span>}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** A calm 3-band scale: green for strong, indigo for partial, amber (not red) for big gaps. */
function scoreBand(value: number): { label: string; stroke: string; tone: BadgeTone } {
  if (value >= 75)
    return { label: "Strong match", stroke: "stroke-success-solid", tone: "success" };
  if (value >= 50) return { label: "Partial match", stroke: "stroke-accent", tone: "accent" };
  return { label: "Big gaps to close", stroke: "stroke-warning-solid", tone: "warning" };
}

function ScoreGauge({ value, size = "lg" }: { value: number; size?: "sm" | "lg" }) {
  const r = 52;
  const c = 2 * Math.PI * r;
  const band = scoreBand(value);
  return (
    <div className={cn("relative shrink-0", size === "lg" ? "size-36" : "size-16")}>
      <svg viewBox="0 0 120 120" className="size-full -rotate-90" aria-hidden>
        <circle
          cx="60"
          cy="60"
          r={r}
          fill="none"
          strokeWidth="10"
          className="stroke-surface-sunken"
        />
        <circle
          cx="60"
          cy="60"
          r={r}
          fill="none"
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - value / 100)}
          className={cn(
            band.stroke,
            "transition-[stroke-dashoffset] duration-700 motion-reduce:transition-none",
          )}
        />
      </svg>
      <span
        role="img"
        aria-label={`Match score ${value} out of 100: ${band.label}`}
        className="absolute inset-0 flex flex-col items-center justify-center"
      >
        <span
          aria-hidden
          className={cn("font-semibold tabular-nums", size === "lg" ? "text-4xl" : "text-lg")}
        >
          {value}
        </span>
        {size === "lg" && (
          <span aria-hidden className="text-fg-subtle text-xs">
            / 100
          </span>
        )}
      </span>
    </div>
  );
}

const VERDICT: Record<Verdict, { label: string; tone: BadgeTone; rank: number }> = {
  no_evidence: { label: "Gap", tone: "danger", rank: 0 },
  weak_evidence: { label: "Weak evidence", tone: "warning", rank: 1 },
  strong_evidence: { label: "Strong evidence", tone: "success", rank: 2 },
};

type Filter = "all" | Verdict;
const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "no_evidence", label: "Gaps" },
  { id: "weak_evidence", label: "Weak" },
  { id: "strong_evidence", label: "Strong" },
];

/** The product's differentiator: the quote was found word for word in the uploaded CV. */
function VerifiedBadge() {
  return (
    <span className="bg-success-soft text-success-fg ring-success-solid/25 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset">
      <Check className="size-3.5" strokeWidth={2.5} />
      Verified in your CV
    </span>
  );
}

function GapRow({ g }: { g: GapItem }) {
  const v = VERDICT[g.verdict];
  return (
    <li
      className={cn(
        "border-border bg-surface space-y-2.5 rounded-xl border border-l-4 p-4",
        g.verdict === "no_evidence" && "border-l-danger-solid",
        g.verdict === "weak_evidence" && "border-l-warning-solid",
        g.verdict === "strong_evidence" && "border-l-success-solid",
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">{g.skill}</span>
        <Badge tone={v.tone}>{v.label}</Badge>
      </div>
      {g.evidence_quote ? (
        <figure className="space-y-2">
          <blockquote className="border-border-strong text-fg-muted border-l-2 pl-3 text-sm italic">
            &ldquo;{g.evidence_quote}&rdquo;
          </blockquote>
          {g.quote_verified && (
            <figcaption>
              <VerifiedBadge />
            </figcaption>
          )}
        </figure>
      ) : (
        <p className="text-fg-subtle text-sm">No evidence found in your CV.</p>
      )}
      <p className="text-fg-muted text-sm">{g.reason}</p>
    </li>
  );
}

function sortGaps(items: GapItem[]): GapItem[] {
  // Gaps first: they are what the user came for. Stable within the same verdict (JD order).
  return items
    .map((g, i) => ({ g, i }))
    .sort((a, b) => VERDICT[a.g.verdict].rank - VERDICT[b.g.verdict].rank || a.i - b.i)
    .map(({ g }) => g);
}

function SkillsSection({ gaps }: { gaps: GapItem[] }) {
  const [filter, setFilter] = useState<Filter>("all");
  const count = (v: Verdict) => gaps.filter((g) => g.verdict === v).length;
  const shown = filter === "all" ? gaps : gaps.filter((g) => g.verdict === filter);
  const groups = [
    { label: "Must-have", items: sortGaps(shown.filter((g) => g.importance === "must_have")) },
    {
      label: "Nice-to-have",
      items: sortGaps(shown.filter((g) => g.importance === "nice_to_have")),
    },
  ];

  return (
    <div className="space-y-5">
      <div role="group" aria-label="Filter skills" className="flex flex-wrap gap-2">
        {FILTERS.map((f) => {
          const n = f.id === "all" ? gaps.length : count(f.id);
          const active = filter === f.id;
          return (
            <button
              key={f.id}
              type="button"
              aria-pressed={active}
              onClick={() => setFilter(f.id)}
              className={cn(
                "inline-flex min-h-9 items-center gap-1.5 rounded-full border px-3 text-sm font-medium transition-colors",
                active
                  ? "border-accent bg-accent text-accent-fg"
                  : "border-border-strong bg-surface text-fg-muted hover:bg-surface-sunken hover:text-fg",
                focusRing,
              )}
            >
              {f.label}
              <span className={cn("tabular-nums", active ? "opacity-90" : "text-fg-subtle")}>
                {n}
              </span>
            </button>
          );
        })}
      </div>

      {shown.length === 0 ? (
        <p className="text-fg-subtle text-sm" role="status">
          Nothing in this group.
        </p>
      ) : (
        groups.map(({ label, items }) =>
          items.length ? (
            <div key={label} className="space-y-3">
              <h3 className="text-fg-subtle text-xs font-semibold tracking-wide uppercase">
                {label}
              </h3>
              <ul className="space-y-3">
                {items.map((g, i) => (
                  <GapRow key={`${g.skill}-${g.verdict}-${i}`} g={g} />
                ))}
              </ul>
            </div>
          ) : null,
        )
      )}
    </div>
  );
}

function hostname(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function PlanDay({ d, defaultOpen }: { d: PrepDay; defaultOpen: boolean }) {
  return (
    <li>
      <details open={defaultOpen} className="group border-border rounded-xl border">
        <summary
          className={cn(
            "flex min-h-12 cursor-pointer list-none items-center gap-3 rounded-xl px-3 py-2 [&::-webkit-details-marker]:hidden",
            "hover:bg-surface-muted",
            focusRing,
          )}
        >
          <span className="bg-accent-soft text-accent-soft-fg flex size-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold">
            <span className="sr-only">Day </span>
            {d.day}
          </span>
          <span className="min-w-0 flex-1 font-medium">{d.focus}</span>
          <span className="text-fg-subtle hidden text-xs sm:inline">
            {d.tasks.length} task{d.tasks.length === 1 ? "" : "s"}
          </span>
          <ChevronDown className="text-fg-subtle size-4 shrink-0 transition-transform group-open:rotate-180 motion-reduce:transition-none" />
        </summary>
        <div className="space-y-2 px-4 pt-1 pb-4 sm:pl-14">
          <ul className="text-fg-muted list-disc space-y-1 pl-5 text-sm">
            {d.tasks.map((t, i) => (
              <li key={i}>{t}</li>
            ))}
          </ul>
          {d.resource_urls.length > 0 && (
            <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
              {d.resource_urls.map((u, i) => (
                <a
                  key={`${u}-${i}`}
                  href={u}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={cn(
                    "text-link inline-flex items-center gap-1 rounded underline underline-offset-2 hover:no-underline",
                    focusRing,
                  )}
                >
                  {hostname(u)}
                  <ExternalLink className="size-3.5" />
                  <span className="sr-only"> (opens in a new tab)</span>
                </a>
              ))}
            </p>
          )}
        </div>
      </details>
    </li>
  );
}

// ------------------------------------------------------------------ main view

export function AnalysisView({ sessionId }: { sessionId: string }) {
  const [s, setS] = useState<State>(INITIAL);
  // No token in this browser, or the server doesn't know it (wrong / expired session).
  const [noToken, setNoToken] = useState(false);
  const started = useRef(false);

  useEffect(() => {
    if (!getToken(sessionId)) {
      setNoToken(true);
      return;
    }
    if (started.current) return; // avoid a double run in React Strict Mode
    started.current = true;
    const controller = new AbortController();

    (async () => {
      try {
        const saved = await getAnalysis(sessionId);
        if (saved) {
          setS({
            ...INITIAL,
            done: true,
            restored: true,
            roleTitle: saved.role_title,
            score: { match_score: saved.match_score, breakdown: saved.breakdown },
            gaps: saved.gaps,
            strengths: saved.strengths,
            questions: saved.likely_questions,
            plan: saved.prep_plan,
          });
          return;
        }
        let finished = false;
        for await (const ev of streamAnalysis(sessionId, controller.signal)) {
          if (ev.event === "done" || ev.event === "error") finished = true;
          if (ev.event === "error" && ev.data.code === "session_not_found") {
            setNoToken(true);
            return;
          }
          setS((prev) => {
            switch (ev.event) {
              case "status":
                // "waiting" / "slow" only change the message, not the progress step.
                return STEP_IDS.has(ev.data.step)
                  ? { ...prev, step: ev.data.step, message: ev.data.message }
                  : { ...prev, message: ev.data.message };
              case "profiles":
                return { ...prev, profiles: ev.data, roleTitle: ev.data.role_title };
              case "score":
                return { ...prev, score: ev.data };
              case "gaps":
                return { ...prev, gaps: ev.data.gaps };
              case "insights":
                return {
                  ...prev,
                  strengths: ev.data.strengths,
                  questions: ev.data.likely_questions,
                  plan: ev.data.prep_plan,
                };
              case "done":
                return {
                  ...prev,
                  done: true,
                  roleTitle: ev.data.role_title,
                  score: { match_score: ev.data.match_score, breakdown: ev.data.breakdown },
                  gaps: ev.data.gaps,
                  strengths: ev.data.strengths,
                  questions: ev.data.likely_questions,
                  plan: ev.data.prep_plan,
                };
              case "error":
                return { ...prev, error: ev.data };
            }
          });
        }
        // e.g. a proxy or the platform closed the stream: never leave the page spinning.
        if (!finished && !controller.signal.aborted)
          setS((prev) => ({ ...prev, error: STREAM_ENDED }));
      } catch (e) {
        if (controller.signal.aborted) return;
        if (e instanceof ApiError && e.code === "session_not_found") {
          setNoToken(true);
          return;
        }
        setS((prev) => ({
          ...prev,
          error: {
            code: e instanceof ApiError ? e.code : "network",
            message:
              e instanceof ApiError ? e.message : "Connection lost. Please refresh to try again.",
          },
        }));
      }
    })();

    return () => controller.abort();
  }, [sessionId]);

  if (noToken) {
    return (
      <Notice tone="warning" title="We can't open this session here">
        <p>
          This session belongs to another browser, or it was cleared or has expired. For privacy,
          sessions can only be opened on the device that created them.
        </p>
        <ButtonLink href="/start" variant="secondary" size="sm" className="mt-2">
          Start a new one
        </ButtonLink>
      </Notice>
    );
  }

  const stopped = s.error !== null;
  const interviewHref = `/session/${sessionId}/interview`;
  const count = (v: Verdict) => s.gaps?.filter((g) => g.verdict === v).length ?? 0;

  return (
    <div className="space-y-6">
      <header className="space-y-3">
        <h1 className="text-2xl font-semibold tracking-tight text-balance sm:text-3xl">
          {s.roleTitle
            ? `Your match for ${s.roleTitle}`
            : s.error
              ? "Analysis stopped"
              : "Analyzing your CV…"}
        </h1>
        {!s.done && !s.error && (
          <p className="text-fg-muted" aria-live="polite">
            {s.message ?? "Starting…"}
          </p>
        )}
        {s.done ? (
          <p className="text-fg-subtle flex items-center gap-1.5 text-sm" role="status">
            <Check className="text-success-fg size-4" />
            Analysis complete
            {s.restored ? " · reopened from your saved session" : ""}
          </p>
        ) : (
          <Progress step={s.step} done={s.done} stopped={s.error !== null} />
        )}
      </header>

      {s.error && (
        <Notice tone="error" title={s.error.message}>
          <Button
            variant="secondary"
            size="sm"
            className="mt-2"
            onClick={() => window.location.reload()}
          >
            Try again
          </Button>
        </Notice>
      )}

      {s.done && s.score && (
        <UiCard
          tone="raised"
          className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between"
        >
          <div className="flex items-center gap-4">
            <ScoreGauge value={s.score.match_score} size="sm" />
            <div className="space-y-1">
              <Badge tone={scoreBand(s.score.match_score).tone}>
                {scoreBand(s.score.match_score).label}
              </Badge>
              <p className="text-fg-muted text-sm">
                <span className="text-fg font-medium">{count("strong_evidence")} strong</span>
                {" · "}
                {count("weak_evidence")} weak
                {" · "}
                <span className="text-danger-fg font-medium">
                  {count("no_evidence")} gap{count("no_evidence") === 1 ? "" : "s"}
                </span>
              </p>
            </div>
          </div>
          <ButtonLink href={interviewHref} size="lg" className="w-full sm:w-auto">
            Start mock interview
            <ArrowRight className="size-4" />
          </ButtonLink>
        </UiCard>
      )}

      <Section id="score" title="Match score">
        {s.score ? (
          <div className="flex flex-col gap-6 sm:flex-row sm:items-center">
            <div className="flex flex-col items-center gap-2">
              <ScoreGauge value={s.score.match_score} />
              <p className="text-fg-muted text-sm font-medium">
                {scoreBand(s.score.match_score).label}
              </p>
            </div>
            <div className="flex-1 space-y-4 text-sm">
              {(
                [
                  ["Must-have skills", s.score.breakdown.must_have],
                  ["Nice-to-have skills", s.score.breakdown.nice_to_have],
                  ["Seniority fit", s.score.breakdown.seniority_fit],
                ] as const
              ).map(([label, c]) => (
                <div key={label}>
                  <div className="flex justify-between gap-2">
                    <span className="font-medium">
                      {label}{" "}
                      <span className="text-fg-subtle font-normal">
                        ({Math.round(c.weight * 100)}% of score)
                      </span>
                    </span>
                    <span className="tabular-nums">{Math.round(c.score * 100)}%</span>
                  </div>
                  <div className="bg-surface-sunken mt-1.5 h-2 overflow-hidden rounded-full">
                    <div
                      className="bg-accent h-full rounded-full"
                      style={{ width: `${c.score * 100}%` }}
                    />
                  </div>
                  <p className="text-fg-subtle mt-1">{c.detail}</p>
                </div>
              ))}
              <details className="group text-fg-muted">
                <summary
                  className={cn(
                    "text-link inline-flex cursor-pointer list-none items-center gap-1 rounded font-medium [&::-webkit-details-marker]:hidden",
                    focusRing,
                  )}
                >
                  How is this calculated?
                  <ChevronDown className="size-4 transition-transform group-open:rotate-180 motion-reduce:transition-none" />
                </summary>
                <p className="bg-surface-sunken text-fg mt-2 rounded-lg px-3 py-2 font-mono text-xs">
                  {s.score.breakdown.formula}
                </p>
              </details>
            </div>
          </div>
        ) : (
          <Pending stopped={stopped} />
        )}
      </Section>

      <Section id="skills" title="Skills vs. this job">
        {s.gaps ? <SkillsSection gaps={s.gaps} /> : <Pending lines={5} stopped={stopped} />}
      </Section>

      <div className="grid gap-6 lg:grid-cols-2">
        <Section id="strengths" title="Strengths to highlight">
          {s.strengths && s.strengths.length === 0 ? (
            <p className="text-fg-muted text-sm">
              We couldn&apos;t find CV evidence for this job&apos;s skills yet. Use the{" "}
              <a href="#plan" className={cn("text-link rounded underline", focusRing)}>
                7-day prep plan
              </a>{" "}
              to build some, then add it to your CV.
            </p>
          ) : s.strengths ? (
            <ul className="space-y-4">
              {s.strengths.map((st, i) => (
                <li key={`${st.title}-${i}`} className="space-y-1">
                  <p className="font-medium">{st.title}</p>
                  <p className="text-fg-muted text-sm">{st.why_it_matters}</p>
                  {st.evidence_quote && (
                    <p className="border-border-strong text-fg-subtle border-l-2 pl-3 text-sm italic">
                      &ldquo;{st.evidence_quote}&rdquo;
                    </p>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <Pending stopped={stopped} />
          )}
        </Section>

        <Section id="questions" title="Likely interview questions">
          {s.questions ? (
            <div className="space-y-4">
              {s.questions.map((g, i) => (
                <div key={`${g.topic}-${i}`}>
                  <p className="font-medium">{g.topic}</p>
                  <ul className="text-fg-muted mt-1 list-disc space-y-1 pl-5 text-sm">
                    {g.questions.map((q, i) => (
                      <li key={i}>{q}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          ) : (
            <Pending stopped={stopped} />
          )}
        </Section>
      </div>

      <Section
        id="plan"
        title="Your 7-day prep plan"
        aside={
          s.plan && s.plan.length > 1 ? (
            <span className="text-fg-subtle text-xs">Open a day to see its tasks</span>
          ) : undefined
        }
      >
        {s.plan ? (
          <ol className="space-y-2">
            {s.plan.map((d, i) => (
              <PlanDay key={d.day} d={d} defaultOpen={i === 0} />
            ))}
          </ol>
        ) : (
          <Pending lines={7} stopped={stopped} />
        )}
      </Section>

      {s.done && (
        <UiCard
          tone="muted"
          className="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between"
        >
          <div className="space-y-1">
            <p className="font-medium">Ready to practise?</p>
            <p className="text-fg-muted text-sm">
              Take the AI mock interview: about 6 questions tailored to your CV and this job, with
              follow-ups.
            </p>
          </div>
          <ButtonLink href={interviewHref} className="w-full shrink-0 sm:w-auto">
            Start interview
            <ArrowRight className="size-4" />
          </ButtonLink>
        </UiCard>
      )}

      {(s.done || s.error) && (
        <p className="text-fg-subtle text-sm">
          <Link href="/start" className={cn("rounded underline hover:no-underline", focusRing)}>
            Analyze another CV or job
          </Link>
        </p>
      )}
    </div>
  );
}
