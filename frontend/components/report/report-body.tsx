import type { ReactNode } from "react";

import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { cn } from "@/components/ui/cn";
import type {
  AnswerLevel,
  AnswerSpeech,
  DimensionScore,
  Flag,
  HiringVerdict,
  PrepDay,
  QuestionReport,
  Readiness,
  ReadinessBand,
  SpeechSummary,
  Theme,
} from "@/lib/types";

// ------------------------------------------------------------------ shared bits

const BAND_TONE: Record<ReadinessBand, BadgeTone> = {
  not_ready: "warning", // never red on a first try (research brief: "Avoid")
  getting_there: "accent",
  interview_ready: "success",
  strong: "success",
};

const LEVEL_TONE: Record<AnswerLevel, BadgeTone> = {
  below_junior: "warning",
  junior: "accent",
  mid: "success",
  senior: "success",
};

const VERDICT_TONE: Record<HiringVerdict, BadgeTone> = {
  strong_yes: "success",
  lean_yes: "success",
  lean_no: "warning",
  no: "warning",
};

/** Anchor id for a question card: "Q3" -> "q3", "Q3.1" -> "q3" (follow-ups live in Q3). */
export function cardId(label: string) {
  return `q${label.replace(/^Q/i, "").split(".")[0]}`;
}

function RefLink({ label }: { label: string }) {
  return (
    <a
      href={`#${cardId(label)}`}
      className="text-link rounded font-medium underline-offset-2 hover:underline"
    >
      {label}
    </a>
  );
}

export function SectionCard({
  id,
  title,
  children,
  className,
}: {
  id?: string;
  title: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Card
      as="section"
      aria-labelledby={id ? `${id}-h` : undefined}
      className={cn("report-block", className)}
    >
      <h2 id={id ? `${id}-h` : undefined} className="mb-4 text-lg font-semibold tracking-tight">
        {title}
      </h2>
      {children}
    </Card>
  );
}

/** Static placeholder while the AI write-up is pending; static (no pulse) once it failed. */
export function Pending({ lines = 3, failed = false }: { lines?: number; failed?: boolean }) {
  if (failed)
    return (
      <p className="text-fg-muted text-sm">This part could not be written. Try again above.</p>
    );
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

function Gauge({ value, label }: { value: number; label: string }) {
  const r = 52;
  const c = 2 * Math.PI * r;
  return (
    <svg
      viewBox="0 0 120 120"
      className="size-32 shrink-0 sm:size-36"
      role="img"
      aria-label={label}
    >
      <circle cx="60" cy="60" r={r} fill="none" strokeWidth="10" className="stroke-border" />
      <circle
        cx="60"
        cy="60"
        r={r}
        fill="none"
        strokeWidth="10"
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={c * (1 - value / 100)}
        transform="rotate(-90 60 60)"
        className="stroke-accent print-exact transition-[stroke-dashoffset] duration-700 motion-reduce:transition-none"
      />
      <text x="60" y="68" textAnchor="middle" className="fill-fg text-3xl font-semibold">
        {value}
      </text>
    </svg>
  );
}

// ------------------------------------------------------------------ 2. readiness hero

export function ReadinessHero({ r }: { r: Readiness }) {
  return (
    <Card as="section" tone="raised" aria-labelledby="readiness-h" className="report-block">
      <div className="flex flex-col gap-6 sm:flex-row sm:items-center">
        <Gauge value={r.score} label={`Readiness ${r.score} out of 100, ${r.band_label}`} />
        <div className="min-w-0 flex-1 space-y-2">
          <p className="text-fg-muted text-sm font-medium">Interview readiness</p>
          <h2 id="readiness-h" className="text-3xl font-semibold tracking-tight sm:text-4xl">
            {r.band_label}{" "}
            <span className="text-fg-muted text-2xl font-medium tabular-nums">{r.score}/100</span>
          </h2>
          <p className="text-fg-muted text-sm tabular-nums">
            Interview {r.interview_score}
            {r.match_score !== null && <> · CV match {r.match_score}</>}
          </p>
          {r.next_band_label && r.points_to_next_band !== null && (
            <p className="text-sm">
              <Badge tone={BAND_TONE[r.band]}>
                {r.points_to_next_band} {r.points_to_next_band === 1 ? "point" : "points"} to{" "}
                {r.next_band_label}
              </Badge>{" "}
              <span className="text-fg-muted">The fixes below are the fastest way up.</span>
            </p>
          )}
          <details className="text-fg-muted text-sm">
            <summary className="text-link cursor-pointer font-medium">
              How is this calculated?
            </summary>
            <p className="bg-surface-sunken mt-2 rounded-lg p-3 font-mono text-xs leading-relaxed">
              {r.formula}
            </p>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              <li>
                Each answer is scored 1–5 on relevance (20%), technical accuracy (25%), depth (25%),
                structure (15%) and communication (15%) against a written rubric with example
                answers. Technical accuracy is skipped on behavioural and role-fit questions.
              </li>
              <li>A question with a follow-up counts 70% main answer, 30% follow-up.</li>
              <li>
                Not scored: your accent, your appearance, filler words or pace. Delivery numbers are
                guidance only.
              </li>
            </ul>
          </details>
        </div>
      </div>
    </Card>
  );
}

// ------------------------------------------------------------------ 3. top fixes / 8. strengths

export function ThemeList({ themes, numbered = false }: { themes: Theme[]; numbered?: boolean }) {
  if (!themes.length) return <p className="text-fg-muted text-sm">Nothing to add here.</p>;
  const List = numbered ? "ol" : "ul";
  return (
    <List className="space-y-4">
      {themes.map((t, i) => (
        <li key={`${t.title}-${i}`} className="flex gap-3">
          {numbered && (
            <span className="bg-accent-soft text-accent-soft-fg flex size-7 shrink-0 items-center justify-center rounded-full text-sm font-semibold">
              {i + 1}
            </span>
          )}
          <div className="space-y-1">
            <p className="font-medium">{t.title}</p>
            <p className="text-fg-muted text-sm">{t.detail}</p>
            {t.answer_refs.length > 0 && (
              <p className="text-fg-subtle text-xs">
                Based on{" "}
                {t.answer_refs.map((ref, j) => (
                  <span key={ref}>
                    {j > 0 && ", "}
                    <RefLink label={ref} />
                  </span>
                ))}
              </p>
            )}
          </div>
        </li>
      ))}
    </List>
  );
}

// ------------------------------------------------------------------ 4. competency strip

export function CompetencyStrip({ questions }: { questions: QuestionReport[] }) {
  const rows = (questions[0]?.dimensions ?? []).map((d) => {
    const scores = questions
      .map((q) => q.dimensions.find((x) => x.key === d.key)?.score)
      .filter((s): s is number => typeof s === "number");
    const avg = scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null;
    return { key: d.key, label: d.label, avg, n: scores.length };
  });
  return (
    <ul className="space-y-3">
      {rows.map((row) => (
        <li
          key={row.key}
          className="grid grid-cols-[9rem_1fr_auto] items-center gap-3 text-sm sm:grid-cols-[11rem_1fr_auto]"
        >
          <span className="font-medium">{row.label}</span>
          <span className="bg-surface-sunken h-2 rounded-full" aria-hidden>
            {row.avg !== null && (
              <span
                className="bg-accent print-exact block h-2 rounded-full"
                style={{ width: `${(row.avg / 5) * 100}%` }}
              />
            )}
          </span>
          <span className="text-fg-muted tabular-nums">
            {row.avg === null ? "N/A" : `${row.avg.toFixed(1)} / 5`}
            <span className="sr-only">
              {row.avg === null ? " not applicable" : ` average over ${row.n} answers`}
            </span>
          </span>
        </li>
      ))}
    </ul>
  );
}

// ------------------------------------------------------------------ 5. hiring-manager view

function FlagList({ flags, good }: { flags: Flag[]; good: boolean }) {
  if (!flags.length) return <p className="text-fg-muted text-sm">None stood out.</p>;
  return (
    <ul className="space-y-3">
      {flags.map((f, i) => (
        <li
          key={`${f.title}-${i}`}
          className={cn(
            "rounded-xl border-l-4 py-1 pl-3",
            good ? "border-success-solid" : "border-warning-solid",
          )}
        >
          <p className="font-medium">
            {f.title}{" "}
            <span className="text-fg-subtle text-xs">
              (<RefLink label={f.answer_ref} />)
            </span>
          </p>
          <p className="text-fg-muted text-sm">{f.detail}</p>
          {f.quote && f.quote_verified && (
            <p className="text-fg-muted mt-1 text-sm italic">You said: “{f.quote}”</p>
          )}
        </li>
      ))}
    </ul>
  );
}

export function EmployerSection({
  verdict,
  verdictLabel,
  reaction,
  green,
  red,
}: {
  verdict: HiringVerdict;
  verdictLabel: string;
  reaction: string;
  green: Flag[];
  red: Flag[];
}) {
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={VERDICT_TONE[verdict]}>Signal: {verdictLabel}</Badge>
        <span className="text-fg-subtle text-xs">
          Simulated. Practice feedback, not a hiring decision.
        </span>
      </div>
      <blockquote className="border-border-strong text-fg border-l-4 pl-4 text-pretty">
        {reaction}
      </blockquote>
      <div className="grid gap-6 md:grid-cols-2">
        <div>
          <h3 className="text-success-fg mb-2 text-sm font-semibold">Green flags</h3>
          <FlagList flags={green} good />
        </div>
        <div>
          <h3 className="text-warning-fg mb-2 text-sm font-semibold">Red flags</h3>
          <FlagList flags={red} good={false} />
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ 6. question cards

/** Transcript with verified evidence quotes marked in place (case-insensitive match). */
function MarkedText({ text, quotes }: { text: string; quotes: string[] }) {
  const lower = text.toLowerCase();
  const hits = quotes
    .map((q) => ({ q, at: lower.indexOf(q.toLowerCase()) }))
    .filter((h) => h.at >= 0)
    .sort((a, b) => a.at - b.at);
  const parts: ReactNode[] = [];
  let pos = 0;
  for (const h of hits) {
    if (h.at < pos) continue; // overlapping quote: keep the first
    parts.push(text.slice(pos, h.at));
    parts.push(
      <mark key={h.at} className="bg-accent-soft text-fg print-exact rounded px-0.5">
        {text.slice(h.at, h.at + h.q.length)}
      </mark>,
    );
    pos = h.at + h.q.length;
  }
  parts.push(text.slice(pos));
  return <p className="text-sm leading-relaxed whitespace-pre-line">{parts}</p>;
}

function Dots({ score }: { score: number | null }) {
  if (score === null) return <span className="text-fg-subtle text-xs">N/A</span>;
  return (
    <span className="inline-flex gap-1" aria-hidden>
      {[1, 2, 3, 4, 5].map((i) => (
        <span
          key={i}
          className={cn(
            "print-exact size-2.5 rounded-full",
            i <= score ? "bg-accent" : "bg-border-strong",
          )}
        />
      ))}
    </span>
  );
}

function DimensionRow({ d, transcript }: { d: DimensionScore; transcript: string }) {
  const inText =
    d.evidence_quote && transcript.toLowerCase().includes(d.evidence_quote.toLowerCase());
  return (
    <li>
      <details className="group">
        <summary
          className="flex cursor-pointer items-center justify-between gap-3 py-1 text-sm"
          aria-label={`${d.label}: ${d.score === null ? "not applicable" : `${d.score} of 5`}. Show why`}
        >
          <span>{d.label}</span>
          <span className="flex items-center gap-2">
            <Dots score={d.score} />
            {d.score !== null && (
              <span className="text-fg-muted w-8 text-right tabular-nums">{d.score}/5</span>
            )}
          </span>
        </summary>
        <div className="text-fg-muted space-y-1 pb-2 text-sm">
          <p>{d.justification}</p>
          {d.evidence_quote && !inText && <p className="italic">You said: “{d.evidence_quote}”</p>}
        </div>
      </details>
    </li>
  );
}

function Delivery({ s }: { s: AnswerSpeech }) {
  const fillers = Object.entries(s.filler_breakdown).sort((a, b) => b[1] - a[1]);
  return (
    <p className="text-fg-muted text-sm">
      <span className="text-fg font-medium">Delivery: </span>
      {s.words_per_minute !== null && <>{Math.round(s.words_per_minute)} WPM · </>}
      {s.filler_count} {s.filler_count === 1 ? "filler" : "fillers"}
      {fillers.length > 0 && (
        <>
          {" "}
          (
          {fillers
            .slice(0, 3)
            .map(([w, n]) => `“${w}” ×${n}`)
            .join(", ")}
          )
        </>
      )}
      {" · "}
      {s.long_pauses} long {s.long_pauses === 1 ? "pause" : "pauses"}
    </p>
  );
}

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-1">
      <h4 className="text-fg-subtle text-xs font-semibold tracking-wide uppercase">{title}</h4>
      {children}
    </div>
  );
}

export function QuestionCard({ q, open }: { q: QuestionReport; open: boolean }) {
  const quotes = q.dimensions.map((d) => d.evidence_quote).filter((x): x is string => !!x);
  const fu = q.follow_up;
  const delta = fu ? fu.average - q.average : 0;
  return (
    <li id={cardId(q.label)} className="report-card scroll-mt-6">
      <details open={open} className="border-border bg-surface rounded-2xl border">
        <summary className="flex cursor-pointer flex-wrap items-center gap-x-3 gap-y-1 p-4 sm:p-5">
          <span className="font-semibold">{q.label}</span>
          <span className="text-fg-muted text-sm capitalize">
            {q.type.replace("_", " ")}
            {q.competency && <> · {q.competency.replaceAll("_", " ")}</>}
          </span>
          <span className="ml-auto flex items-center gap-2">
            <Badge tone={LEVEL_TONE[q.level]}>{q.level_label}</Badge>
            <span className="font-semibold tabular-nums">{q.score}/100</span>
          </span>
          <span className="text-fg w-full text-sm text-pretty">{q.question}</span>
        </summary>
        <div className="border-border space-y-4 border-t p-4 sm:p-5">
          <Block title="Your answer">
            <MarkedText text={q.answer} quotes={quotes} />
          </Block>
          <Block title="Scores">
            <ul className="divide-border divide-y">
              {q.dimensions.map((d) => (
                <DimensionRow key={d.key} d={d} transcript={q.answer} />
              ))}
            </ul>
          </Block>
          {q.what_interviewer_wanted && (
            <Block title="What the interviewer wanted">
              <p className="text-sm">{q.what_interviewer_wanted}</p>
            </Block>
          )}
          {q.improved_answer && (
            <Block title="Try saying it like this">
              <blockquote className="border-accent bg-accent-soft/40 rounded-r-lg border-l-4 p-3 text-sm">
                {q.improved_answer}
              </blockquote>
            </Block>
          )}
          {q.tip && (
            <Block title="One thing to practise">
              <p className="text-sm">{q.tip}</p>
            </Block>
          )}
          {fu && (
            <div className="bg-surface-muted border-border space-y-2 rounded-xl border p-3">
              <p className="flex flex-wrap items-center gap-2 text-sm">
                <span className="font-semibold">Follow-up {fu.label}</span>
                <span className="tabular-nums">{fu.score}/100</span>
                <span
                  className={cn(
                    "text-xs font-medium",
                    delta >= 0.5
                      ? "text-success-fg"
                      : delta <= -0.5
                        ? "text-warning-fg"
                        : "text-fg-muted",
                  )}
                >
                  {delta >= 0.5 ? "↑ up" : delta <= -0.5 ? "↓ down" : "→ steady"} vs. main answer
                </span>
              </p>
              <p className="text-sm font-medium">{fu.question}</p>
              <p className="text-fg-muted text-sm whitespace-pre-line">{fu.answer}</p>
              <p className="text-sm">{fu.handling}</p>
              {fu.tip && <p className="text-fg-muted text-sm">Tip: {fu.tip}</p>}
            </div>
          )}
          {q.speech && <Delivery s={q.speech} />}
        </div>
      </details>
    </li>
  );
}

// ------------------------------------------------------------------ 7. speech

const PACE_MIN = 80;
const PACE_MAX = 200;
const pct = (wpm: number) =>
  `${((Math.min(PACE_MAX, Math.max(PACE_MIN, wpm)) - PACE_MIN) / (PACE_MAX - PACE_MIN)) * 100}%`;

export function SpeechSection({ s }: { s: SpeechSummary }) {
  const minutes = s.rows.reduce((t, r) => t + (r.duration_seconds ?? 0), 0) / 60;
  const perMin = minutes > 0 ? s.filler_total / minutes : null;
  const top = Object.entries(s.filler_breakdown).slice(0, 3);
  return (
    <div className="space-y-5">
      <p className="text-sm">{s.guidance}</p>
      <figure className="space-y-2">
        <figcaption className="text-fg-muted text-xs">
          Speaking pace per answer (shaded: roughly 120–160 WPM; ranges vary by coach)
        </figcaption>
        <div
          className="bg-surface-sunken relative h-8 rounded-lg"
          role="img"
          aria-label={`Average pace ${s.average_wpm ?? "unknown"} words per minute`}
        >
          <span
            className="bg-success-soft print-exact absolute inset-y-0 rounded"
            style={{ left: pct(120), width: `calc(${pct(160)} - ${pct(120)})` }}
          />
          {s.rows
            .filter((r) => r.words_per_minute !== null)
            .map((r) => (
              <span
                key={r.label}
                className="text-fg-muted absolute top-0 -translate-x-1/2 text-[10px] font-medium"
                style={{ left: pct(r.words_per_minute as number) }}
                title={`${r.label}: ${Math.round(r.words_per_minute as number)} WPM`}
              >
                {r.label}
                <span className="bg-fg-muted mx-auto mt-0.5 block h-3 w-0.5" />
              </span>
            ))}
          {s.average_wpm !== null && (
            <span
              className="bg-accent print-exact absolute inset-y-0 w-1 -translate-x-1/2 rounded"
              style={{ left: pct(s.average_wpm) }}
            />
          )}
        </div>
        <div className="text-fg-subtle flex justify-between text-[10px] tabular-nums">
          <span>{PACE_MIN}</span>
          <span>120</span>
          <span>160</span>
          <span>{PACE_MAX} WPM</span>
        </div>
      </figure>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="text-sm">
          <p className="font-medium">
            Filler words: {s.filler_total}
            {perMin !== null && (
              <span className="text-fg-muted font-normal"> ({perMin.toFixed(1)} per minute)</span>
            )}
          </p>
          {top.length > 0 && (
            <p className="mt-1 flex flex-wrap gap-1.5">
              {top.map(([w, n]) => (
                <Badge key={w}>
                  {w} ×{n}
                </Badge>
              ))}
            </p>
          )}
          <p className="text-fg-muted mt-1">Under about 3 per minute sounds polished.</p>
        </div>
        <div className="text-sm">
          <p className="font-medium">Long pauses (over 2 s): {s.long_pauses_total}</p>
          <p className="text-fg-muted mt-1">
            A 2–3 second pause to think is fine. Many long pauses in one answer can sound unsure.
          </p>
        </div>
      </div>
      <table className="w-full text-left text-sm tabular-nums">
        <caption className="sr-only">Delivery per answer</caption>
        <thead className="text-fg-subtle text-xs">
          <tr>
            <th className="py-1 font-medium">Answer</th>
            <th className="py-1 font-medium">WPM</th>
            <th className="py-1 font-medium">Fillers</th>
            <th className="py-1 font-medium">Pauses</th>
            <th className="py-1 font-medium">Length</th>
          </tr>
        </thead>
        <tbody className="divide-border divide-y">
          {s.rows.map((r) => (
            <tr key={r.label}>
              <td className="py-1">{r.label}</td>
              <td className="py-1">
                {r.words_per_minute === null ? "—" : Math.round(r.words_per_minute)}
              </td>
              <td className="py-1">{r.filler_count}</td>
              <td className="py-1">{r.long_pauses}</td>
              <td className="py-1">
                {r.duration_seconds === null ? "—" : `${Math.round(r.duration_seconds)} s`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-fg-subtle text-xs">
        Delivery numbers are guidance only and don&apos;t change your score. Urdu and Hinglish
        fillers (matlab, yani, acha) are counted the same way as English ones.
      </p>
    </div>
  );
}

// ------------------------------------------------------------------ 9. plan

function hostname(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function PlanList({ plan, footer }: { plan: PrepDay[]; footer?: ReactNode }) {
  return (
    <ol className="space-y-2">
      {plan.map((d) => (
        <li key={d.day} className="report-card">
          <details open={d.day === 1} className="border-border rounded-xl border">
            <summary className="flex cursor-pointer items-center gap-3 p-3">
              <span className="bg-accent-soft text-accent-soft-fg flex size-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold">
                {d.day}
              </span>
              <span className="font-medium">{d.focus}</span>
            </summary>
            <div className="space-y-2 px-3 pb-3 pl-14">
              <ul className="text-fg-muted list-disc space-y-1 pl-4 text-sm">
                {d.tasks.map((t, i) => (
                  <li key={i}>{t}</li>
                ))}
              </ul>
              {d.resource_urls.length > 0 && (
                <p className="flex flex-wrap gap-3 text-sm">
                  {d.resource_urls.map((u, i) => (
                    <a
                      key={`${u}-${i}`}
                      href={u}
                      target="_blank"
                      rel="noopener noreferrer"
                      referrerPolicy="no-referrer"
                      className="text-link underline hover:no-underline"
                    >
                      {hostname(u)}
                    </a>
                  ))}
                </p>
              )}
              {d.day === 7 && footer}
            </div>
          </details>
        </li>
      ))}
    </ol>
  );
}

// ------------------------------------------------------------------ helpers for routes

/** The weakest main answer's card starts open (the one to work on first). */
export function weakestLabel(questions: QuestionReport[]): string | null {
  if (!questions.length) return null;
  return questions.reduce((a, b) => (b.score < a.score ? b : a)).label;
}

export function formatDate(iso: string | null | undefined, withTime = false) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  });
}
