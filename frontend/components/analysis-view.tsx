"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

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
  error: null,
};

// ------------------------------------------------------------------ small pieces

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-zinc-200 p-6 dark:border-zinc-800">
      <h2 className="mb-4 text-lg font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="space-y-3" aria-hidden>
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="h-4 animate-pulse rounded bg-zinc-200 motion-reduce:animate-none dark:bg-zinc-800"
          style={{ width: `${90 - i * 12}%` }}
        />
      ))}
    </div>
  );
}

function Progress({ step, done }: { step: string | null; done: boolean }) {
  const current = done
    ? STEPS.length
    : Math.max(
        0,
        STEPS.findIndex((s) => s.id === step),
      );
  return (
    <ol className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4" aria-label="Analysis progress">
      {STEPS.map((s, i) => {
        const state = i < current ? "done" : i === current && !done ? "active" : "todo";
        return (
          <li
            key={s.id}
            aria-current={state === "active" ? "step" : undefined}
            className={`rounded-lg border px-3 py-2 ${
              state === "done"
                ? "border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-300"
                : state === "active"
                  ? "border-indigo-400 bg-indigo-50 text-indigo-800 dark:border-indigo-700 dark:bg-indigo-950 dark:text-indigo-300"
                  : "border-zinc-200 text-zinc-500 dark:border-zinc-800"
            }`}
          >
            {state === "done" ? "✓ " : state === "active" ? "… " : ""}
            {s.label}
          </li>
        );
      })}
    </ol>
  );
}

function ScoreGauge({ value }: { value: number }) {
  const r = 52;
  const c = 2 * Math.PI * r;
  const color = value >= 75 ? "#059669" : value >= 50 ? "#d97706" : "#dc2626";
  return (
    <svg
      viewBox="0 0 120 120"
      className="h-36 w-36"
      role="img"
      aria-label={`Match score ${value} out of 100`}
    >
      <circle
        cx="60"
        cy="60"
        r={r}
        fill="none"
        stroke="currentColor"
        strokeWidth="10"
        className="text-zinc-200 dark:text-zinc-800"
      />
      <circle
        cx="60"
        cy="60"
        r={r}
        fill="none"
        stroke={color}
        strokeWidth="10"
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={c * (1 - value / 100)}
        transform="rotate(-90 60 60)"
        className="transition-[stroke-dashoffset] duration-700 motion-reduce:transition-none"
      />
      <text x="60" y="66" textAnchor="middle" className="fill-current text-3xl font-semibold">
        {value}
      </text>
    </svg>
  );
}

const VERDICT: Record<Verdict, { label: string; cls: string }> = {
  strong_evidence: {
    label: "Strong evidence",
    cls: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  },
  weak_evidence: {
    label: "Weak evidence",
    cls: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  },
  no_evidence: { label: "Gap", cls: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300" },
};

function GapRow({ g }: { g: GapItem }) {
  const v = VERDICT[g.verdict];
  return (
    <li className="space-y-2 rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{g.skill}</span>
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${v.cls}`}>{v.label}</span>
      </div>
      {g.evidence_quote ? (
        <blockquote className="border-l-4 border-zinc-300 pl-3 text-sm text-zinc-700 italic dark:border-zinc-700 dark:text-zinc-300">
          “{g.evidence_quote}”
          <span className="ml-2 text-xs text-zinc-500 not-italic">verified in your CV</span>
        </blockquote>
      ) : (
        <p className="text-sm text-zinc-500">No evidence found in your CV.</p>
      )}
      <p className="text-sm text-zinc-600 dark:text-zinc-400">{g.reason}</p>
    </li>
  );
}

function hostname(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

// ------------------------------------------------------------------ main view

export function AnalysisView({ sessionId }: { sessionId: string }) {
  const [s, setS] = useState<State>(INITIAL);
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
            roleTitle: saved.role_title,
            score: { match_score: saved.match_score, breakdown: saved.breakdown },
            gaps: saved.gaps,
            strengths: saved.strengths,
            questions: saved.likely_questions,
            plan: saved.prep_plan,
          });
          return;
        }
        for await (const ev of streamAnalysis(sessionId, controller.signal)) {
          setS((prev) => {
            switch (ev.event) {
              case "status":
                return { ...prev, step: ev.data.step, message: ev.data.message };
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
      } catch (e) {
        if (controller.signal.aborted) return;
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
      <div className="rounded-xl bg-amber-50 p-6 text-amber-900 dark:bg-amber-950 dark:text-amber-200">
        This session belongs to another browser, or it was cleared. For privacy, sessions can only
        be opened on the device that created them.{" "}
        <Link href="/start" className="font-medium underline">
          Start a new one
        </Link>
        .
      </div>
    );
  }

  const must = s.gaps?.filter((g) => g.importance === "must_have") ?? [];
  const nice = s.gaps?.filter((g) => g.importance === "nice_to_have") ?? [];

  return (
    <div className="space-y-6">
      <header className="space-y-3">
        <h1 className="text-3xl font-semibold tracking-tight">
          {s.roleTitle ? `Your match for ${s.roleTitle}` : "Analyzing your CV…"}
        </h1>
        {!s.done && !s.error && (
          <p className="text-zinc-600 dark:text-zinc-400" aria-live="polite">
            {s.message ?? "Starting…"}
          </p>
        )}
        <Progress step={s.step} done={s.done} />
      </header>

      {s.error && (
        <div
          role="alert"
          className="rounded-xl bg-red-50 p-4 text-red-800 dark:bg-red-950 dark:text-red-300"
        >
          <p className="font-medium">{s.error.message}</p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-2 text-sm font-medium underline"
          >
            Try again
          </button>
        </div>
      )}

      <Card title="Match score">
        {s.score ? (
          <div className="flex flex-col gap-6 sm:flex-row sm:items-center">
            <ScoreGauge value={s.score.match_score} />
            <div className="flex-1 space-y-3 text-sm">
              {(
                [
                  ["Must-have skills", s.score.breakdown.must_have],
                  ["Nice-to-have skills", s.score.breakdown.nice_to_have],
                  ["Seniority fit", s.score.breakdown.seniority_fit],
                ] as const
              ).map(([label, c]) => (
                <div key={label}>
                  <div className="flex justify-between">
                    <span className="font-medium">
                      {label} <span className="text-zinc-500">({Math.round(c.weight * 100)}%)</span>
                    </span>
                    <span>{Math.round(c.score * 100)}%</span>
                  </div>
                  <div className="mt-1 h-2 rounded bg-zinc-200 dark:bg-zinc-800">
                    <div
                      className="h-2 rounded bg-indigo-600"
                      style={{ width: `${c.score * 100}%` }}
                    />
                  </div>
                  <p className="mt-1 text-zinc-500">{c.detail}</p>
                </div>
              ))}
              <details className="text-zinc-500">
                <summary className="cursor-pointer">How is this calculated?</summary>
                <p className="mt-2">{s.score.breakdown.formula}</p>
              </details>
            </div>
          </div>
        ) : (
          <Skeleton />
        )}
      </Card>

      <Card title="Skills vs. this job">
        {s.gaps ? (
          <div className="space-y-6">
            {[
              ["Must-have", must],
              ["Nice-to-have", nice],
            ].map(([label, items]) =>
              (items as GapItem[]).length ? (
                <div key={label as string} className="space-y-3">
                  <h3 className="text-sm font-semibold text-zinc-500 uppercase">
                    {label as string}
                  </h3>
                  <ul className="space-y-3">
                    {(items as GapItem[]).map((g) => (
                      <GapRow key={g.skill} g={g} />
                    ))}
                  </ul>
                </div>
              ) : null,
            )}
          </div>
        ) : (
          <Skeleton lines={5} />
        )}
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Strengths to highlight">
          {s.strengths && s.strengths.length === 0 ? (
            <p className="text-sm text-zinc-500">
              We couldn&apos;t find CV evidence for this job&apos;s skills yet. Use the prep plan
              below to build some, then add it to your CV.
            </p>
          ) : s.strengths ? (
            <ul className="space-y-4">
              {s.strengths.map((st) => (
                <li key={st.title}>
                  <p className="font-medium">{st.title}</p>
                  <p className="text-sm text-zinc-600 dark:text-zinc-400">{st.why_it_matters}</p>
                  {st.evidence_quote && (
                    <p className="mt-1 text-sm text-zinc-500 italic">“{st.evidence_quote}”</p>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <Skeleton />
          )}
        </Card>

        <Card title="Likely interview questions">
          {s.questions ? (
            <div className="space-y-4">
              {s.questions.map((g) => (
                <div key={g.topic}>
                  <p className="font-medium">{g.topic}</p>
                  <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-zinc-700 dark:text-zinc-300">
                    {g.questions.map((q) => (
                      <li key={q}>{q}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          ) : (
            <Skeleton />
          )}
        </Card>
      </div>

      <Card title="Your 7-day prep plan">
        {s.plan ? (
          <ol className="space-y-4">
            {s.plan.map((d) => (
              <li key={d.day} className="flex gap-4">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-sm font-semibold text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300">
                  {d.day}
                </span>
                <div className="space-y-1">
                  <p className="font-medium">{d.focus}</p>
                  <ul className="list-disc pl-5 text-sm text-zinc-700 dark:text-zinc-300">
                    {d.tasks.map((t) => (
                      <li key={t}>{t}</li>
                    ))}
                  </ul>
                  {d.resource_urls.length > 0 && (
                    <p className="flex flex-wrap gap-2 text-sm">
                      {d.resource_urls.map((u) => (
                        <a
                          key={u}
                          href={u}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-indigo-600 underline hover:no-underline dark:text-indigo-400"
                        >
                          {hostname(u)}
                        </a>
                      ))}
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <Skeleton lines={7} />
        )}
      </Card>

      {s.done && (
        <div className="flex flex-col items-start gap-2 rounded-2xl bg-indigo-50 p-6 dark:bg-indigo-950">
          <p className="font-medium">Ready to practise?</p>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            The AI mock interview (6 tailored questions with follow-ups) is coming in the next
            update.
          </p>
          <button
            type="button"
            disabled
            className="mt-2 rounded-lg bg-indigo-600 px-5 py-3 font-medium text-white opacity-50"
          >
            Start interview (coming soon)
          </button>
        </div>
      )}
    </div>
  );
}
