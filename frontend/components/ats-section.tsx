"use client";

import { Badge, type BadgeTone } from "@/components/ui/badge";
import { cn, focusRing } from "@/components/ui/cn";
import { Alert, Check, ChevronDown } from "@/components/ui/icons";
import { Notice } from "@/components/ui/notice";
import { ScoreGauge } from "@/components/score-gauge";
import type { AtsCategory, AtsCheck, AtsReport, KeywordHit, PrepDay } from "@/lib/types";

/** Same calm palette as the match score: amber, not red, for the lowest band. */
export function atsBand(value: number): { label: string; stroke: string; tone: BadgeTone } {
  if (value >= 80)
    return { label: "Ready to submit", stroke: "stroke-success-solid", tone: "success" };
  if (value >= 60) return { label: "A few fixes", stroke: "stroke-accent", tone: "accent" };
  return { label: "Fix before applying", stroke: "stroke-warning-solid", tone: "warning" };
}

export function AtsGauge({ ats, size = "lg" }: { ats: AtsReport; size?: "sm" | "lg" }) {
  const band = atsBand(ats.score);
  return (
    <ScoreGauge
      value={ats.score}
      size={size}
      label="ATS readiness"
      bandLabel={band.label}
      stroke={band.stroke}
    />
  );
}

export const ATS_DISCLAIMER =
  "ATS readiness estimates how cleanly your CV parses and how well it covers this job's keywords. " +
  "It is not the score any specific ATS (Workday, Greenhouse…) gives, and no tool can see that.";

const CATEGORY: Record<AtsCategory, string> = {
  readability: "Readability",
  keywords: "Keyword coverage",
  content: "Content quality",
};

const STATUS: Record<
  AtsCheck["status"],
  { label: string; tone: BadgeTone; border: string; rank: number }
> = {
  fail: { label: "Fix", tone: "danger", border: "border-l-danger-solid", rank: 0 },
  warn: { label: "Improve", tone: "warning", border: "border-l-warning-solid", rank: 1 },
  pass: { label: "Pass", tone: "success", border: "border-l-success-solid", rank: 2 },
  info: { label: "Tip", tone: "neutral", border: "border-l-border-strong", rank: 3 },
};

const SECTION_NAMES: Record<string, string> = {
  top: "Header",
  summary: "Summary",
  experience: "Experience",
  projects: "Projects",
  skills: "Skills",
  education: "Education",
  certifications: "Certifications",
};

function Bars({ ats }: { ats: AtsReport }) {
  const rows = [
    ["Readability", ats.readability],
    ["Keyword coverage", ats.keywords],
    ["Content quality", ats.content],
  ] as const;
  return (
    <div className="flex-1 space-y-4 text-sm">
      {rows.map(([label, c]) => (
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
            <div className="bg-accent h-full rounded-full" style={{ width: `${c.score * 100}%` }} />
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
          {ats.formula}
        </p>
        <p className="mt-2 text-xs">
          Same CV and job, same score, every time: every check is a rule in code, not a model&apos;s
          opinion.
        </p>
      </details>
    </div>
  );
}

function planDayFor(term: string, plan: PrepDay[] | null): number | null {
  if (!plan) return null;
  const t = term.toLowerCase();
  const day = plan.find((d) => [d.focus, ...d.tasks].some((s) => s.toLowerCase().includes(t)));
  return day ? day.day : null;
}

function Chip({ hit, plan }: { hit: KeywordHit; plan: PrepDay[] | null }) {
  const tone =
    hit.status === "exact"
      ? "border-success-solid/30 bg-success-soft text-success-fg"
      : hit.status === "alias_only"
        ? "border-warning-solid/30 bg-warning-soft text-warning-fg"
        : "border-danger-solid/25 bg-danger-soft text-danger-fg";
  const where = hit.sections.map((s) => SECTION_NAMES[s] ?? s).join(", ");
  const meta =
    hit.status === "exact"
      ? `×${hit.count}${where ? ` · in ${where}` : ""}`
      : hit.status === "alias_only"
        ? `you wrote “${hit.matched_as}”`
        : hit.importance === "must_have"
          ? "required"
          : hit.importance === "title"
            ? "job title"
            : hit.importance === "credential"
              ? "credential"
              : "preferred";
  if (hit.status === "exact") {
    return (
      <li
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm",
          tone,
        )}
      >
        <Check className="size-3.5" strokeWidth={2.5} />
        <span className="font-medium">{hit.term}</span>
        <span className="text-xs opacity-80">{meta}</span>
      </li>
    );
  }
  const day =
    hit.status === "missing" && !hit.proven_not_searchable ? planDayFor(hit.term, plan) : null;
  return (
    <li className="max-w-full has-[details[open]]:basis-full">
      <details className="group">
        <summary
          className={cn(
            "inline-flex max-w-full cursor-pointer list-none items-center gap-1.5 rounded-full border px-3 py-1 text-sm [&::-webkit-details-marker]:hidden",
            tone,
            focusRing,
          )}
        >
          <span className="truncate font-medium">{hit.term}</span>
          <span className="text-xs opacity-80">{meta}</span>
          {hit.proven_not_searchable && (
            <span className="bg-surface text-success-fg ring-success-solid/25 rounded-full px-1.5 text-[11px] font-semibold ring-1">
              You have evidence
            </span>
          )}
          <ChevronDown className="size-3.5 shrink-0 transition-transform group-open:rotate-180 motion-reduce:transition-none" />
        </summary>
        <div className="border-border bg-surface text-fg-muted mt-2 max-w-prose space-y-2 rounded-xl border p-3 text-sm">
          {hit.proven_not_searchable && hit.evidence_quote && (
            <p>
              You have evidence for &lsquo;{hit.term}&rsquo; but not the words the job uses, so a
              recruiter searching &lsquo;{hit.term}&rsquo; won&apos;t find you.{" "}
              <a href="#skills" className={cn("text-link rounded underline", focusRing)}>
                See the verified quote
              </a>
            </p>
          )}
          <p className="text-fg">{hit.where_to_add}</p>
          {day && (
            <p>
              <a href="#plan" className={cn("text-link rounded underline", focusRing)}>
                Day {day} of your prep plan
              </a>{" "}
              covers it.
            </p>
          )}
          <p className="text-fg-subtle text-xs">
            In the job post {hit.jd_count}× · in your CV {hit.count}×
          </p>
        </div>
      </details>
    </li>
  );
}

function Keywords({ hits, plan }: { hits: KeywordHit[]; plan: PrepDay[] | null }) {
  const rank = { must_have: 0, title: 1, credential: 2, nice_to_have: 3 } as const;
  const sorted = [...hits].sort((a, b) => rank[a.importance] - rank[b.importance]);
  const groups = [
    {
      id: "missing",
      label: "Missing",
      hint: "Add only what's true. Open a term to see where.",
      items: sorted.filter((h) => h.status === "missing"),
    },
    {
      id: "alias",
      label: "Written differently",
      hint: "Some ATS searches miss abbreviations: write both forms once.",
      items: sorted.filter((h) => h.status === "alias_only"),
    },
    { id: "found", label: "Found", hint: null, items: sorted.filter((h) => h.status === "exact") },
  ];
  return (
    <div className="space-y-4">
      <h3 className="font-semibold">This job&apos;s keywords in your CV</h3>
      {groups.map((g) =>
        g.items.length ? (
          <div key={g.id} className="space-y-2">
            <p className="text-fg-subtle text-xs font-semibold tracking-wide uppercase">
              {g.label} <span className="tabular-nums">({g.items.length})</span>
              {g.hint && (
                <span className="ml-2 font-normal tracking-normal normal-case">{g.hint}</span>
              )}
            </p>
            <ul className="flex flex-wrap gap-2" aria-label={`${g.label} keywords`}>
              {g.items.map((h, i) => (
                <Chip key={`${h.term}-${i}`} hit={h} plan={plan} />
              ))}
            </ul>
          </div>
        ) : null,
      )}
    </div>
  );
}

function CheckRow({ c }: { c: AtsCheck }) {
  const st = STATUS[c.status];
  return (
    <li
      className={cn(
        "border-border bg-surface space-y-1.5 rounded-xl border border-l-4 p-4",
        st.border,
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">{c.title}</span>
        <Badge tone={st.tone}>{st.label}</Badge>
      </div>
      <p className="text-fg-muted text-sm">{c.message}</p>
      {c.evidence && (
        <blockquote className="border-border-strong text-fg-muted border-l-2 pl-3 text-sm break-words italic">
          &ldquo;{c.evidence}&rdquo;
        </blockquote>
      )}
      {c.fix && (
        <p className="text-sm">
          <span className="font-medium">Fix: </span>
          {c.fix}
        </p>
      )}
    </li>
  );
}

function Checklist({ checks }: { checks: AtsCheck[] }) {
  const sorted = [...checks].sort((a, b) => STATUS[a.status].rank - STATUS[b.status].rank);
  return (
    <div className="space-y-5">
      <h3 className="font-semibold">Checklist</h3>
      {(Object.keys(CATEGORY) as AtsCategory[]).map((cat) => {
        const mine = sorted.filter((c) => c.category === cat);
        const open = mine.filter((c) => c.status === "fail" || c.status === "warn");
        const passed = mine.filter((c) => c.status === "pass");
        const tips = mine.filter((c) => c.status === "info");
        if (!mine.length) return null;
        return (
          <div key={cat} className="space-y-3">
            <h4 className="text-fg-subtle text-xs font-semibold tracking-wide uppercase">
              {CATEGORY[cat]}
            </h4>
            {open.length > 0 && (
              <ul className="space-y-3">
                {open.map((c) => (
                  <CheckRow key={c.id} c={c} />
                ))}
              </ul>
            )}
            {passed.length > 0 && (
              <details className="group">
                <summary
                  className={cn(
                    "text-success-fg inline-flex cursor-pointer list-none items-center gap-1.5 rounded text-sm font-medium [&::-webkit-details-marker]:hidden",
                    focusRing,
                  )}
                >
                  <Check className="size-4" />
                  {passed.length} check{passed.length === 1 ? "" : "s"} passed
                  <ChevronDown className="size-4 transition-transform group-open:rotate-180 motion-reduce:transition-none" />
                </summary>
                <ul className="mt-3 space-y-3">
                  {passed.map((c) => (
                    <CheckRow key={c.id} c={c} />
                  ))}
                </ul>
              </details>
            )}
            {tips.length > 0 && (
              <ul className="text-fg-muted list-disc space-y-1 pl-5 text-sm">
                {tips.map((c) => (
                  <li key={c.id}>
                    <span className="text-fg font-medium">{c.title}:</span> {c.message}
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Explainer() {
  return (
    <details className="group border-border rounded-xl border">
      <summary
        className={cn(
          "flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 rounded-xl px-4 py-2 font-medium [&::-webkit-details-marker]:hidden",
          "hover:bg-surface-muted",
          focusRing,
        )}
      >
        What this score is, and isn&apos;t
        <ChevronDown className="text-fg-subtle size-4 transition-transform group-open:rotate-180 motion-reduce:transition-none" />
      </summary>
      <div className="text-fg-muted space-y-2 px-4 pb-4 text-sm">
        <p>
          <span className="text-fg font-medium">It is</span> a check of the two things ATSs really
          do with a CV: the parser turns your file into fields (tables, columns, headers and text
          boxes can scramble or lose text), and recruiters then search those fields by skills and
          job title. Everything is computed in code from rules you can read above.
        </p>
        <p>
          <span className="text-fg font-medium">It isn&apos;t</span> your score in Workday,
          Greenhouse, Lever or Taleo: those rankings are private, set by each recruiter per job, and
          no outside tool can see them. The popular claim that &ldquo;75% of CVs are rejected by an
          ATS&rdquo; traces back to a 2012 sales pitch with no published data. Most automatic
          rejections come from screening questions on the application form (see the list below), not
          from CV formatting.
        </p>
        <p>
          80+ is a good target. Chasing 100 usually means keyword stuffing, which recruiters notice.
        </p>
      </div>
    </details>
  );
}

export function AtsSection({ ats, plan }: { ats: AtsReport; plan: PrepDay[] | null }) {
  const band = atsBand(ats.score);
  const hidden = ats.checks.find((c) => c.id === "R8" && c.status === "fail");
  return (
    <div className="space-y-6">
      {ats.gated && (
        <Notice tone="warning" title={`Capped at 40: an ATS can't reliably read this CV's text`}>
          <p>
            Until the text can be read, keywords can&apos;t be found either. Fix the &ldquo;Text
            layer&rdquo; or &ldquo;Clean characters&rdquo; item first.
          </p>
        </Notice>
      )}
      {hidden && (
        <Notice tone="error" title="Your CV contains hidden or copied text">
          <p>{hidden.message}</p>
        </Notice>
      )}
      <div className="flex flex-col gap-6 sm:flex-row sm:items-center">
        <div className="flex flex-col items-center gap-2">
          <AtsGauge ats={ats} />
          <Badge tone={band.tone}>{band.label}</Badge>
        </div>
        <Bars ats={ats} />
      </div>
      <p className="text-fg-subtle text-sm">{ATS_DISCLAIMER}</p>
      <Keywords hits={ats.keyword_hits} plan={plan} />
      <Checklist checks={ats.checks} />
      {ats.knockouts.length > 0 && (
        <div className="bg-surface-muted border-border space-y-2 rounded-xl border p-4 text-sm">
          <p className="flex items-center gap-2 font-medium">
            <Alert className="text-fg-subtle size-4" />
            Knockout readiness
          </p>
          <p className="text-fg-muted">
            This job may ask screening questions on these. Your answers to them, not your CV layout,
            are what can reject an application automatically.
          </p>
          <ul className="text-fg-muted list-disc space-y-1 pl-5">
            {ats.knockouts.map((k) => (
              <li key={k}>{k}</li>
            ))}
          </ul>
        </div>
      )}
      <Explainer />
    </div>
  );
}
