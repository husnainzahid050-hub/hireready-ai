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
  {
    skill: "Docker",
    tone: "warning",
    verdict: "Weak evidence",
    quote: "Skills: Docker, Git, Linux",
  },
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
      {/* soft glow behind the card; decorative. A plain gradient, no blur filter (costly paint on phones). */}
      <div
        aria-hidden
        className="absolute -inset-8 -z-10 bg-[radial-gradient(closest-side,color-mix(in_srgb,var(--accent)_18%,transparent),transparent)]"
      />
      <Card tone="raised" padded={false} className="overflow-hidden">
        <div className="border-border bg-surface-muted flex items-center gap-1.5 border-b px-4 py-2.5">
          <span aria-hidden className="bg-border-strong size-2.5 rounded-full" />
          <span aria-hidden className="bg-border-strong size-2.5 rounded-full" />
          <span aria-hidden className="bg-border-strong size-2.5 rounded-full" />
          <span className="text-fg-subtle ml-2 truncate text-xs">
            Sample: Sara Ahmed (fictional) for Junior AI Engineer
          </span>
          <Badge tone="neutral" className="ml-auto shrink-0">
            Sample data
          </Badge>
        </div>

        <div className="space-y-5 p-5">
          <div className="flex items-center gap-5">
            <div className="relative">
              <Gauge value={SCORE} />
              <span className="absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-2xl font-semibold tabular-nums">{SCORE}</span>
                <span className="text-fg-subtle text-[0.65rem]">/ 100</span>
              </span>
            </div>
            <ul className="flex-1 space-y-2.5 text-xs">
              {BREAKDOWN.map((b, i) => (
                <li key={b.label}>
                  <div className="flex justify-between gap-2">
                    <span className="text-fg-muted">
                      {b.label} <span className="text-fg-subtle">({b.weight}%)</span>
                    </span>
                    <span className="font-medium tabular-nums">{b.value}%</span>
                  </div>
                  <div className="bg-surface-sunken mt-1 h-1.5 overflow-hidden rounded-full">
                    <div
                      className="animate-grow-x bg-accent h-full origin-left rounded-full"
                      style={{ width: `${b.value}%`, animationDelay: `${150 + i * 120}ms` }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          </div>

          <ul className="space-y-2.5">
            {SKILLS.map((s) => (
              <li key={s.skill} className="border-border bg-surface rounded-xl border p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">{s.skill}</span>
                  <Badge tone={s.tone}>{s.verdict}</Badge>
                </div>
                {s.quote ? (
                  <p className="border-border-strong text-fg-muted mt-2 border-l-2 pl-2.5 text-xs">
                    “{s.quote}”
                    <span className="text-success-fg mt-1 flex items-center gap-1 text-[0.7rem]">
                      <Check className="size-3.5" /> verified in the CV
                    </span>
                  </p>
                ) : (
                  <p className="text-fg-subtle mt-2 text-xs">No evidence found in the CV.</p>
                )}
              </li>
            ))}
          </ul>
        </div>
      </Card>
      <figcaption className="text-fg-subtle mt-3 text-center text-xs">
        Sample data for a made-up candidate, not a real person. Your own analysis appears only after
        you upload your CV, and only in your browser.
      </figcaption>
    </figure>
  );
}
