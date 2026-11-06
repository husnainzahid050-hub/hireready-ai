// Presentational pieces of the interview page. No hooks here, so the skeleton can also be
// rendered by the server page shell as the <Suspense> fallback.

import type { AnswerFeedback, Question, QuestionType } from "@/lib/types";

export const FOCUS_RING =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 dark:focus-visible:outline-indigo-400";

export const BUTTON_PRIMARY = `inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-indigo-600 px-5 py-2.5 font-medium text-white transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-indigo-600 ${FOCUS_RING}`;

export const BUTTON_SECONDARY = `inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium transition-colors hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-900 ${FOCUS_RING}`;

const TYPE_LABEL: Record<QuestionType, string> = {
  technical: "Technical",
  project: "Project deep-dive",
  gap_probe: "Skill check",
  behavioral: "Behavioral",
  role_fit: "Role fit",
  follow_up: "Follow-up",
};

export function questionLabel(q: Question): string {
  return q.is_follow_up ? TYPE_LABEL.follow_up : TYPE_LABEL[q.type];
}

/** What the interviewer is doing. "speaking" is driven by speechSynthesis in voice mode (Phase 4). */
export type InterviewerStatus = "listening" | "thinking" | "speaking";

const STATUS_TEXT: Record<InterviewerStatus, string> = {
  listening: "Waiting for your answer",
  thinking: "Interviewer is thinking…",
  speaking: "Interviewer is speaking…",
};

export function SpeakingIndicator({ status }: { status: InterviewerStatus }) {
  const active = status !== "listening";
  return (
    <div className="flex items-center gap-3">
      <span
        aria-hidden
        className={`relative flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-sm font-semibold text-white ${
          active ? "bg-indigo-600" : "bg-zinc-500 dark:bg-zinc-600"
        }`}
      >
        AI
        {active && (
          <span className="absolute inset-0 animate-ping rounded-full bg-indigo-500 opacity-30 motion-reduce:hidden" />
        )}
      </span>
      <span className="flex h-5 items-end gap-0.5" aria-hidden>
        {[0, 1, 2, 3].map((i) => (
          <span
            key={i}
            className={`w-1 rounded-sm bg-indigo-500 dark:bg-indigo-400 ${
              active
                ? "animate-bars h-full origin-bottom motion-reduce:animate-none"
                : "h-1.5 opacity-50"
            }`}
            style={active ? { animationDelay: `${i * 0.12}s` } : undefined}
          />
        ))}
      </span>
      <span className="text-sm text-zinc-600 dark:text-zinc-400">{STATUS_TEXT[status]}</span>
    </div>
  );
}

export function ProgressHeader({
  question,
  total,
  completed,
}: {
  question: Question | null;
  total: number;
  completed: boolean;
}) {
  const current = completed ? total : (question?.order ?? 1);
  const pct = completed
    ? 100
    : Math.min(100, Math.round(((current - 1) / Math.max(1, total)) * 100));
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">
          {completed ? "Interview complete" : `Question ${current} of ~${total}`}
        </span>
        {question && !completed && (
          <span
            className={`rounded-full px-2 py-0.5 text-xs font-medium ${
              question.is_follow_up
                ? "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200"
                : "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
            }`}
          >
            {questionLabel(question)}
          </span>
        )}
      </div>
      <div
        role="progressbar"
        aria-label="Interview progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        className="h-1.5 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800"
      >
        <div
          className="h-full origin-left rounded-full bg-indigo-600 transition-transform duration-500 motion-reduce:transition-none"
          style={{ transform: `scaleX(${pct / 100})` }}
        />
      </div>
    </div>
  );
}

/**
 * The interviewer: a caption-style card for the current question plus a status indicator.
 * `controls` is the slot for Phase 4 voice controls (mute toggle, replay via speechSynthesis).
 */
export function InterviewerPanel({
  question,
  status,
  controls,
}: {
  question: Question;
  status: InterviewerStatus;
  controls?: React.ReactNode;
}) {
  return (
    <section
      aria-labelledby="current-question-label"
      className="rounded-2xl border border-zinc-200 bg-zinc-50 p-4 sm:p-6 dark:border-zinc-800 dark:bg-zinc-900"
    >
      <div className="flex min-h-11 flex-wrap items-center justify-between gap-3">
        <SpeakingIndicator status={status} />
        {controls}
      </div>
      <h2 id="current-question-label" className="sr-only">
        Current question
      </h2>
      <p className="mt-4 rounded-xl bg-zinc-900 px-4 py-3 text-lg leading-relaxed text-white sm:px-5 sm:py-4 sm:text-xl dark:bg-black dark:ring-1 dark:ring-zinc-800">
        {question.text}
      </p>
      {question.competency && (
        <p className="mt-2 text-xs text-zinc-600 dark:text-zinc-400">
          Topic: <span className="font-medium">{question.competency}</span>
        </p>
      )}
    </section>
  );
}

export function FeedbackCard({ feedback }: { feedback: AnswerFeedback }) {
  return (
    <section
      aria-labelledby="feedback-heading"
      className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4 text-sm sm:p-5 dark:border-emerald-900 dark:bg-emerald-950"
    >
      <h2 id="feedback-heading" className="font-semibold text-emerald-900 dark:text-emerald-200">
        Practice feedback on your last answer
      </h2>
      <p className="mt-1 text-emerald-900 dark:text-emerald-100">{feedback.summary}</p>
      <p className="mt-2 text-emerald-900 dark:text-emerald-100">
        <span className="font-medium">Tip: </span>
        {feedback.tip}
      </p>
    </section>
  );
}

export function Notice({
  tone,
  children,
}: {
  tone: "error" | "warning" | "info";
  children: React.ReactNode;
}) {
  const cls = {
    error: "bg-red-50 text-red-900 dark:bg-red-950 dark:text-red-200",
    warning: "bg-amber-50 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
    info: "bg-indigo-50 text-indigo-900 dark:bg-indigo-950 dark:text-indigo-200",
  }[tone];
  return (
    <div role={tone === "error" ? "alert" : "status"} className={`rounded-xl p-4 text-sm ${cls}`}>
      {children}
    </div>
  );
}

function Bar({ w, h = "h-4" }: { w: string; h?: string }) {
  return (
    <div
      className={`${h} animate-pulse rounded bg-zinc-200 motion-reduce:animate-none dark:bg-zinc-800`}
      style={{ width: w }}
    />
  );
}

/** Same footprint as the interview layout, so swapping it in causes no layout shift. */
export function InterviewSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading interview" className="space-y-6">
      <span className="sr-only">Loading your interview…</span>
      <div className="space-y-2" aria-hidden>
        <Bar w="10rem" />
        <Bar w="100%" h="h-1.5" />
      </div>
      <div
        aria-hidden
        className="space-y-4 rounded-2xl border border-zinc-200 p-4 sm:p-6 dark:border-zinc-800"
      >
        <Bar w="12rem" h="h-11" />
        <Bar w="100%" h="h-20" />
      </div>
      <div aria-hidden className="space-y-2">
        <Bar w="100%" h="h-40" />
      </div>
    </div>
  );
}
