import { cn } from "@/components/ui/cn";
import { Alert, Check } from "@/components/ui/icons";
import type { SpeechMetrics } from "@/lib/types";
import { speechGuidance } from "@/lib/voice";

/** Practice-mode delivery feedback for the last voice answer: pace, fillers, pauses. */
export function SpeechFeedback({ metrics }: { metrics: SpeechMetrics }) {
  const items = speechGuidance(metrics);
  return (
    <section
      aria-labelledby="speech-feedback-heading"
      className="border-border bg-surface shadow-card rounded-2xl border p-4 sm:p-5"
    >
      <h2 id="speech-feedback-heading" className="font-semibold">
        How you sounded
      </h2>
      <dl className="mt-3 grid gap-3 sm:grid-cols-3">
        {items.map((g) => {
          const good = g.tone === "good";
          return (
            <div
              key={g.label}
              className={cn(
                "space-y-1 rounded-xl border p-3 text-sm",
                good
                  ? "border-success-solid/25 bg-success-soft"
                  : "border-warning-solid/30 bg-warning-soft",
              )}
            >
              <dt
                className={cn(
                  "flex items-center gap-1.5 text-xs font-semibold tracking-wide uppercase",
                  good ? "text-success-fg" : "text-warning-fg",
                )}
              >
                {good ? <Check className="size-4" /> : <Alert className="size-4" />}
                {g.label}
                <span className="sr-only">{good ? " (good)" : " (to improve)"}</span>
              </dt>
              <dd className="text-fg text-base font-semibold">{g.value}</dd>
              <dd className="text-fg-muted">{g.advice}</dd>
            </div>
          );
        })}
      </dl>
    </section>
  );
}
