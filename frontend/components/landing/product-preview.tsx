// A static, HTML/CSS-only mock of the analysis page (no screenshot, no video, no image request).
// The numbers follow the real formula: 100 x (0.7 x 0.79 + 0.2 x 0.5 + 0.1 x 1.0) = 75.
import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Check } from "@/components/ui/icons";

const SCORE = 75;

const BREAKDOWN = [
  { label: "Must-have skills", weight: 70, value: 79 },
  { label: "Nice-to-have", weight: 20, value: 50 },
  { label: "Seniority fit", weight: 10, value: 100 },
];

const SKILLS: { skill: string; tone: BadgeTone; verdict: string; quote: string | null }[] = [
  {
    skill: "Python",
    tone: "success",
    verdict: "Strong evidence",
    quote: "Built a RAG assistant in Python and FastAPI that answers support tickets",
  },
  { skill: "Docker", tone: "warning", verdict: "Weak evidence", quote: "Skills: Docker, Git, Linux" },
  { skill: "AWS", tone: "danger", verdict: "Gap", quote: null },
];

function Gauge({ value }: { value: number }) {
  const r = 40;
  const c = 2 * Math.PI * r;
  return (
    <svg viewBox="0 0 100 100" className="size-24 shrink-0 -rotate-90" aria-hidden="true">
      <circle cx="50" cy="50" r={r} fill="none" strokeWidth="9" className="stroke-surface-sunken" />
      <circle
        cx="50"
        cy="50"
        r={r}
        fill="none"
        strokeWidth="9"
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={c * (1 - value / 100)}
        className="stroke-success-solid"
      />
    </svg>
  );
}

export function ProductPreview() {
  return (
    <figure className="relative isolate">
      {/* soft glow behind the card; decorative */}
      <div
        aria-hidden
        className="absolute -inset-4 -z-10 rounded-[2rem] bg-[radial-gradient(60%_60%_at_60%_30%,color-mix(in_srgb,var(--accent)_22%,transparent),transparent)] blur-2xl"
      />
      <Card tone="raised" padded={false} className="overflow-hidden">
        <div className="flex items-center gap-1.5 border-b border-border bg-surface-muted px-4 py-2.5">
          <span aria-hidden className="size-2.5 rounded-full bg-border-strong" />
          <span aria-hidden className="size-2.5 rounded-full bg-border-strong" />
          <span aria-hidden className="size-2.5 rounded-full bg-border-strong" />
          <span className="ml-2 truncate text-xs text-fg-subtle">
            Your match for Junior AI Engineer
          </span>
        </div>

        <div className="space-y-5 p-5">
          <div className="flex items-center gap-5">
            <div className="relative">
              <Gauge value={SCORE} />
              <span className="absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-2xl font-semibold tabular-nums">{SCORE}</span>
                <span className="text-[0.65rem] text-fg-subtle">/ 100</span>
              </span>
            </div>
            <dl className="flex-1 space-y-2.5 text-xs">
              {BREAKDOWN.map((b, i) => (
                <div key={b.label}>
                  <div className="flex justify-between gap-2">
                    <dt className="text-fg-muted">
                      {b.label} <span className="text-fg-subtle">({b.weight}%)</span>
                    </dt>
                    <dd className="font-medium tabular-nums">{b.value}%</dd>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-sunken">
                    <div
                      className="animate-grow-x h-full origin-left rounded-full bg-accent"
                      style={{ width: `${b.value}%`, animationDelay: `${150 + i * 120}ms` }}
                    />
                  </div>
                </div>
              ))}
            </dl>
          </div>

          <ul className="space-y-2.5">
            {SKILLS.map((s) => (
              <li key={s.skill} className="rounded-xl border border-border bg-surface p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">{s.skill}</span>
                  <Badge tone={s.tone}>{s.verdict}</Badge>
                </div>
                {s.quote ? (
                  <p className="mt-2 border-l-2 border-border-strong pl-2.5 text-xs text-fg-muted">
                    “{s.quote}”
                    <span className="mt-1 flex items-center gap-1 text-[0.7rem] text-success-fg">
                      <Check className="size-3.5" /> verified in your CV
                    </span>
                  </p>
                ) : (
                  <p className="mt-2 text-xs text-fg-subtle">No evidence found in your CV.</p>
                )}
              </li>
            ))}
          </ul>
        </div>
      </Card>
      <figcaption className="mt-3 text-center text-xs text-fg-subtle">
        Example output for a fictional candidate. Every quote is checked against the CV in code.
      </figcaption>
    </figure>
  );
}
