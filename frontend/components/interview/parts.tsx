// Presentational pieces of the interview page. No hooks here, so the skeleton can also be
// rendered by the server page shell as the <Suspense> fallback.

import { Badge } from "@/components/ui/badge";
import { buttonClasses } from "@/components/ui/button";
import { cn, focusRing } from "@/components/ui/cn";
import { Check } from "@/components/ui/icons";
import { Notice as UiNotice } from "@/components/ui/notice";
import type { AnswerFeedback, Question, QuestionType } from "@/lib/types";

/** Kept for older call sites; new code should use `focusRing` / `buttonClasses()` directly. */
export const FOCUS_RING = focusRing;
export const BUTTON_PRIMARY = buttonClasses();
export const BUTTON_SECONDARY = buttonClasses({ variant: "secondary" });

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
        className={cn(
          "relative flex size-11 shrink-0 items-center justify-center rounded-full text-sm font-semibold transition-colors motion-reduce:transition-none",
          active
            ? "bg-accent text-accent-fg"
            : "bg-surface-sunken text-fg-muted ring-border ring-1",
        )}
      >
        AI
        {active && (
          <span className="bg-accent absolute inset-0 animate-ping rounded-full opacity-30 motion-reduce:hidden" />
        )}
      </span>
      <span className="flex h-5 items-end gap-0.5" aria-hidden>
        {[0, 1, 2, 3].map((i) => (
          <span
            key={i}
            className={cn(
              "bg-accent w-1 rounded-sm",
              active
                ? "animate-bars h-full origin-bottom motion-reduce:animate-none"
                : "h-1.5 opacity-40",
            )}
            style={active ? { animationDelay: `${i * 0.12}s` } : undefined}
          />
        ))}
      </span>
      <span className="text-fg-muted text-sm">{STATUS_TEXT[status]}</span>
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
          <Badge tone={question.is_follow_up ? "warning" : "neutral"}>
            {questionLabel(question)}
          </Badge>
        )}
      </div>
      <div
        role="progressbar"
        aria-label="Interview progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        className="bg-surface-sunken h-1.5 overflow-hidden rounded-full"
      >
        <div
          className="bg-accent h-full origin-left rounded-full transition-transform duration-500 motion-reduce:transition-none"
          style={{ transform: `scaleX(${pct / 100})` }}
        />
      </div>
    </div>
  );
}

/**
 * The interviewer: a caption-style card for the current question plus a status indicator.
 * `controls` is the slot for the voice controls (replay and mute, via speechSynthesis).
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
      className="border-border bg-surface shadow-card rounded-2xl border p-4 sm:p-6"
    >
      <div className="flex min-h-11 flex-wrap items-center justify-between gap-3">
        <SpeakingIndicator status={status} />
        {controls}
      </div>
      <h2 id="current-question-label" className="sr-only">
        Current question
      </h2>
      <p className="bg-surface-sunken border-accent text-fg mt-4 rounded-xl border-l-4 px-4 py-3 text-lg leading-relaxed font-medium text-pretty sm:px-5 sm:py-4 sm:text-xl">
        {question.text}
      </p>
      {question.competency && (
        <p className="text-fg-subtle mt-2 text-xs">
          Topic: <span className="text-fg-muted font-medium">{question.competency}</span>
        </p>
      )}
    </section>
  );
}

export function FeedbackCard({ feedback }: { feedback: AnswerFeedback }) {
  return (
    <section
      aria-labelledby="feedback-heading"
      className="border-success-solid/25 bg-success-soft text-success-fg rounded-2xl border p-4 text-sm sm:p-5"
    >
      <h2 id="feedback-heading" className="flex items-center gap-1.5 font-semibold">
        <Check className="size-4" />
        Practice feedback on your last answer
      </h2>
      <p className="text-fg mt-1.5">{feedback.summary}</p>
      <p className="text-fg mt-2">
        <span className="text-success-fg font-semibold">Tip: </span>
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
  return <UiNotice tone={tone}>{children}</UiNotice>;
}

function Bar({ w, h = "h-4" }: { w: string; h?: string }) {
  return (
    <div
      className={cn(h, "bg-surface-sunken animate-pulse rounded motion-reduce:animate-none")}
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
      <div aria-hidden className="border-border space-y-4 rounded-2xl border p-4 sm:p-6">
        <Bar w="12rem" h="h-11" />
        <Bar w="100%" h="h-20" />
      </div>
      <div aria-hidden className="space-y-2">
        <Bar w="100%" h="h-40" />
      </div>
    </div>
  );
}
