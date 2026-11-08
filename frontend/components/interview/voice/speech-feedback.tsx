import type { SpeechMetrics } from "@/lib/types";
import { speechGuidance } from "@/lib/voice";

/** Practice-mode delivery feedback for the last voice answer: pace, fillers, pauses. */
export function SpeechFeedback({ metrics }: { metrics: SpeechMetrics }) {
  const items = speechGuidance(metrics);
  return (
    <section
      aria-labelledby="speech-feedback-heading"
      className="rounded-2xl border border-sky-200 bg-sky-50 p-4 text-sm sm:p-5 dark:border-sky-900 dark:bg-sky-950"
    >
      <h2 id="speech-feedback-heading" className="font-semibold text-sky-950 dark:text-sky-100">
        How you sounded
      </h2>
      <dl className="mt-2 grid gap-3 sm:grid-cols-3">
        {items.map((g) => (
          <div key={g.label} className="space-y-0.5">
            <dt className="text-xs font-medium tracking-wide text-sky-900 uppercase dark:text-sky-200">
              {g.label}
            </dt>
            <dd className="font-medium text-sky-950 dark:text-sky-50">
              <span aria-hidden className="mr-1">
                {g.tone === "good" ? "✓" : "!"}
              </span>
              {g.value}
            </dd>
            <dd className="text-sky-900 dark:text-sky-200">{g.advice}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
