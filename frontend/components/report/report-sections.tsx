import type { ReactNode } from "react";

import {
  CompetencyStrip,
  EmployerSection,
  formatDate,
  Pending,
  PlanList,
  QuestionCard,
  ReadinessHero,
  SectionCard,
  SpeechSection,
  ThemeList,
  weakestLabel,
} from "@/components/report/report-body";
import { Badge } from "@/components/ui/badge";
import type { Report, ReportOverview } from "@/lib/types";

export type Synthesis = Pick<
  Report,
  "employer" | "strengths" | "improvements" | "prep_plan" | "open_gaps" | "generated_by"
>;

/**
 * The report in the order the research brief recommends: readiness, top fixes, competencies,
 * hiring-manager view, question cards, delivery, strengths, gaps + plan, footer.
 * `overview` (computed in code) renders at once; `synthesis` (the AI write-up) may still be null.
 */
export function ReportSections({
  overview,
  synthesis,
  failed,
  expiresAt,
  planFooter,
}: {
  overview: ReportOverview;
  synthesis: Synthesis | null;
  failed: boolean;
  expiresAt: string | null;
  planFooter?: ReactNode;
}) {
  const { readiness, questions, speech } = overview;
  const weakest = weakestLabel(questions);
  const expires = formatDate(expiresAt);

  return (
    <div className="space-y-6">
      <ReadinessHero r={readiness} />

      <SectionCard id="fixes" title="Top 3 things to fix">
        {synthesis ? (
          <ThemeList themes={synthesis.improvements.slice(0, 3)} numbered />
        ) : (
          <Pending failed={failed} />
        )}
      </SectionCard>

      <SectionCard id="competencies" title="Across all answers">
        <CompetencyStrip questions={questions} />
      </SectionCard>

      <SectionCard id="employer" title="Simulated hiring-manager reaction">
        {synthesis ? (
          <EmployerSection
            verdict={synthesis.employer.verdict}
            verdictLabel={synthesis.employer.verdict_label}
            reaction={synthesis.employer.reaction}
            green={synthesis.employer.green_flags}
            red={synthesis.employer.red_flags}
          />
        ) : (
          <Pending lines={4} failed={failed} />
        )}
      </SectionCard>

      <section aria-labelledby="answers-h" className="space-y-3">
        <h2 id="answers-h" className="text-lg font-semibold tracking-tight">
          Question by question
        </h2>
        <p className="text-fg-muted text-sm print:hidden">
          Highlighted words are the parts of your answer the scorer quoted as evidence. Your weakest
          answer is open; tap any question to expand it.
        </p>
        <ol className="space-y-3">
          {questions.map((q) => (
            <QuestionCard key={q.label} q={q} open={q.label === weakest} />
          ))}
        </ol>
      </section>

      <SectionCard id="speech" title="How you sounded">
        {speech ? (
          <SpeechSection s={speech} />
        ) : (
          <p className="text-fg-muted text-sm">
            You typed your answers, so there are no pace or filler numbers. Answer by voice next
            time to get delivery feedback.
          </p>
        )}
      </SectionCard>

      <SectionCard id="strengths" title="Strengths to keep">
        {synthesis ? <ThemeList themes={synthesis.strengths} /> : <Pending failed={failed} />}
      </SectionCard>

      <SectionCard id="plan" title="Your refreshed 7-day plan">
        {synthesis ? (
          <div className="space-y-4">
            {synthesis.open_gaps.length > 0 && (
              <p className="flex flex-wrap items-center gap-1.5 text-sm">
                <span className="text-fg-muted">Still open from your CV:</span>
                {synthesis.open_gaps.map((g) => (
                  <Badge key={g} tone="warning">
                    {g}
                  </Badge>
                ))}
              </p>
            )}
            <PlanList plan={synthesis.prep_plan} footer={planFooter} />
          </div>
        ) : (
          <Pending lines={7} failed={failed} />
        )}
      </SectionCard>

      <footer className="text-fg-subtle space-y-1 text-xs">
        {synthesis?.generated_by === "fallback" && (
          <p className="bg-warning-soft text-warning-fg rounded-lg p-3 text-sm">
            The written feedback used a simpler template because the AI service was busy. All scores
            above are the same either way; they are computed from your scored answers.
          </p>
        )}
        <p>
          AI-generated practice feedback from your answers. Scores are practice feedback, not a
          hiring decision. Audio is never stored.
        </p>
        {expires && <p>This report and all session data auto-delete on {expires}.</p>}
      </footer>
    </div>
  );
}
