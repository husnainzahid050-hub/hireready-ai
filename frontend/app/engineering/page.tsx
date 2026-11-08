import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import { ArchitectureDiagram } from "@/components/engineering/architecture-diagram";
import { GITHUB_URL } from "@/components/site/config";
import { DataTable, DocSection, TextLink } from "@/components/site/prose";
import { Badge } from "@/components/ui/badge";
import { ButtonLink } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn, focusRing } from "@/components/ui/cn";
import { ArrowRight, Github } from "@/components/ui/icons";
import { Container } from "@/components/ui/section";

export const ensureStatic = "navigation";

export const metadata: Metadata = {
  title: "Engineering",
  description:
    "How HireReady AI works: architecture, the RAG gap-analysis pipeline, a stateless LangGraph interviewer, design decisions, security and measured latency.",
  alternates: { canonical: "/engineering" },
};

const docUrl = (path: string) => `${GITHUB_URL}/blob/main/${path}`;

const TOC = [
  { id: "architecture", label: "Architecture" },
  { id: "data-flow", label: "Data flow" },
  { id: "decisions", label: "Design decisions" },
  { id: "numbers", label: "Measured numbers" },
  { id: "evals", label: "Evaluation" },
  { id: "security", label: "Security" },
];

const ANALYSIS_FLOW: { title: string; body: string; calls?: string }[] = [
  {
    title: "Validate and extract",
    body: "2 MB, PDF/DOCX only, declared MIME must match the magic bytes, at most 5 pages, parsed off the event loop with a timeout. Only the extracted text is stored, never the file.",
  },
  {
    title: "Profile the CV and the job",
    body: "Two structured-output calls run in parallel against strict JSON schemas. The job profile is cached by a hash of its text, so the sample JD costs nothing after the first run.",
    calls: "1–2 LLM calls",
  },
  {
    title: "Index the CV",
    body: "Heading-aware chunks, embedded in one batched Gemini call (768 dimensions), scoped to this session only.",
  },
  {
    title: "Retrieve and judge",
    body: "For every required skill, hybrid search (pgvector + Postgres full-text, fused with Reciprocal Rank Fusion) finds CV excerpts. One judge call rates each skill strong, weak or none and quotes the CV.",
    calls: "1 LLM call",
  },
  {
    title: "Verify and score in code",
    body: "Each quote must appear verbatim in the CV after normalisation, or the verdict drops to “no evidence”. The match score is arithmetic: 100 × (0.7 must-have + 0.2 nice-to-have + 0.1 seniority).",
  },
  {
    title: "Questions and plan",
    body: "Strengths (each backed by a verified quote), likely questions adapted from the rubric knowledge base, and a 7-day plan limited to allowlisted resource URLs.",
    calls: "1 LLM call",
  },
];

const DECISIONS: { title: string; why: ReactNode; tradeoff: ReactNode }[] = [
  {
    title: "Turn-based voice, not a live audio stream",
    why: "The candidate records one answer, it is transcribed (Groq Whisper), and the next question comes back as text read aloud by the browser. That fits stateless serverless functions and free tiers, always produces captions, and audio never needs to be stored.",
    tradeoff:
      "It feels less like a phone call: there is a pause of a few seconds between turns, and you can't interrupt the interviewer.",
  },
  {
    title: "Hybrid search with Reciprocal Rank Fusion",
    why: "Vector search understands meaning but misses exact terms like “GIL”, “HAVING” or “STAR”; full-text search is the opposite. RRF merges the two by rank (1/(k + rank), k = 50), so their incompatible score scales never need to be compared.",
    tradeoff:
      "Two searches per query and one more SQL function to maintain. Whether it beats vector-only is measured in Phase 8 (hit rate@5, MRR).",
  },
  {
    title: "Evidence quotes are verified, not trusted",
    why: "The model proposes a quote; deterministic code checks that it really is in the CV (case, whitespace, curly quotes, dashes and bullets normalised) and that it doesn't read like an instruction. Unverifiable evidence becomes “no evidence”, and strengths without a verified quote are dropped.",
    tradeoff:
      "A real but paraphrased quote is rejected, so the tool errs on the side of saying “no evidence”.",
  },
  {
    title: "A stateless LangGraph: one turn per request",
    why: "Each answer request loads the interview state (one JSON row), runs the graph for exactly one turn, and saves it. If the LLM fails mid-turn nothing is written, and the client retries safely. Nodes are pure functions, which makes them easy to test.",
    tradeoff:
      "Every turn pays a database read and write, and two answers to the same question at once can race (last write wins).",
  },
  {
    title: "Groq first, Gemini as automatic fallback",
    why: "Groq is fast (answer turns in 2–4 s), but its free tier allows about 8K tokens per minute per model. On a 429, a 5xx or invalid JSON the call falls back to Gemini, with per-provider time budgets so a run can't hang.",
    tradeoff:
      "Fallback turns are much slower (11–15 s measured), and two providers' structured-output quirks have to be handled.",
  },
  {
    title: "Token budgets shape the prompts",
    why: (
      <>
        The first skill judge sent the same CV excerpts once per skill: 7,016 prompt tokens. Now
        each excerpt is sent once with an id and skills reference ids: 1,113 tokens for the same
        information. Each interview answer is a single fast-model call that scores, decides on a
        follow-up and phrases it.
      </>
    ),
    tradeoff:
      "Fewer, denser calls are harder to debug, and the fast model scores a little less carefully than the strong one.",
  },
  {
    title: "Deterministic scoring, explainable to the user",
    why: "LLMs are poor at consistent numbers. Verdicts come from the model, but the match score is computed in code and its formula is shown on the analysis page. Answer scores use string enums (“1”–“5”), anchored 1/3/5 examples and temperature 0.1.",
    tradeoff:
      "A fixed formula can't weigh a skill that matters more for one particular job; it is transparent rather than clever.",
  },
  {
    title: "Static pages and a CSP-friendly diagram",
    why: "The landing, engineering and privacy pages are prerendered (enforced with ensureStatic), and the diagram above is HTML, not Mermaid: the strict Content-Security-Policy allows scripts and images from our own origin only.",
    tradeoff:
      "The diagram is edited by hand in a React component rather than written in Mermaid syntax.",
  },
];

const NUMBERS: ReactNode[][] = [
  ["Time to first analysis event", "0.5–0.7 s", "< 3 s", "Phase 2 QA, live Groq"],
  ["Complete analysis (sample CV)", "17–22 s", "—", "Phase 2, all on Groq"],
  [
    "Complete analysis with Gemini fallback",
    "25–34 s",
    "≤ 50 s budget",
    "QA runs; analysis now has a 50 s budget",
  ],
  ["Re-opening a saved analysis", "< 1 s", "—", "Served from the database, 0 LLM calls"],
  ["LLM calls per analysis", "3–4", "—", "JD profile cached by content hash"],
  ["Interview answer → next question", "1.9–3.7 s", "< 4 s p50", "Groq; ~1.8K prompt tokens"],
  ["Whisper transcription per voice answer", "~0.66 s", "—", "Live smoke test; audio never stored"],
  ["Answer turn on Gemini fallback", "11–15 s", "—", "When Groq's per-minute limit is hit"],
  ["Evidence quotes found verbatim in the CV", "100%", "100%", "6 live QA analyses"],
  ["Rubric knowledge base", "14 competencies, 157 chunks", "—", "Curated markdown, hybrid-indexed"],
  ["Backend tests", "230", "—", "All LLM and network calls mocked"],
];

const EVALS: ReactNode[][] = [
  ["Gap detection", "Precision / recall on 10 labelled CV–JD pairs", "—"],
  ["Evidence faithfulness", "% of quotes verbatim in the CV", "100% after validation"],
  ["Retrieval", "Hit rate@5 and MRR, vector-only vs hybrid (30 queries)", "—"],
  ["Scoring calibration", "% of 30 labelled answers within the expected range", "—"],
  ["Scoring consistency", "Variance when the same answer is scored 3×", "—"],
  ["Injection resistance", "% of adversarial CVs/answers handled safely", "—"],
  ["Latency and cost", "p50/p95 per endpoint, tokens per interview", "Answer turn < 4 s p50"],
];

const SECURITY = [
  "Random 32-byte guest token stored only as a SHA-256 hash, constant-time comparison, and the same 404 for “missing” and “not yours”.",
  "Row Level Security on every table with no anon grants; only the backend uses the service role.",
  "Per-session quotas on every LLM-spending action, atomic in Postgres; per-IP rate limits and Turnstile wired in, switched on with their keys.",
  "Uploads checked for size, MIME, magic bytes and page count, with PDF/DOCX bomb limits and a parse timeout.",
  "CV, JD and transcripts fenced as untrusted data; forged closing tags neutralised; all outputs schema-validated.",
  "Logs carry IDs only: emails are masked and long strings truncated, so CV text never reaches them.",
  "Strict security headers: CSP, HSTS, nosniff, frame-ancestors none, Permissions-Policy.",
];

export default function EngineeringPage() {
  return (
    <main className="py-12 sm:py-16">
      <Container className="space-y-6">
        <header className="max-w-3xl space-y-4">
          <p className="text-link text-sm font-semibold tracking-wide uppercase">Engineering</p>
          <h1 className="text-3xl font-semibold tracking-tight text-balance sm:text-5xl">
            How HireReady works, and why it&apos;s built this way
          </h1>
          <p className="text-fg-muted text-lg text-pretty">
            A RAG pipeline that checks its own evidence, a stateless agent that interviews you one
            turn at a time, and a frontend that stays static where it can. Everything runs on free
            tiers. The numbers below were measured, not estimated.
          </p>
          <div className="flex flex-wrap gap-3 pt-2">
            <ButtonLink href={GITHUB_URL} variant="secondary">
              <Github className="size-4" /> Source on GitHub
            </ButtonLink>
            <ButtonLink href="/start" variant="ghost">
              Try it <ArrowRight className="size-4" />
            </ButtonLink>
          </div>
        </header>
      </Container>

      <Container className="mt-12 grid gap-12 lg:grid-cols-[12rem_1fr] lg:gap-16">
        <nav aria-label="On this page" className="lg:sticky lg:top-6 lg:self-start">
          <p className="mb-3 text-sm font-semibold">On this page</p>
          <ul className="flex flex-wrap gap-2 text-sm lg:flex-col lg:gap-1">
            {TOC.map((t) => (
              <li key={t.id}>
                <a
                  href={`#${t.id}`}
                  className={cn(
                    "border-border text-fg-muted hover:bg-surface-sunken hover:text-fg block rounded-lg border px-3 py-1.5 lg:border-0 lg:px-2",
                    focusRing,
                  )}
                >
                  {t.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <div className="min-w-0 space-y-16">
          <DocSection id="architecture" title="Architecture">
            <p className="text-fg-muted max-w-3xl">
              Two Vercel projects: the Next.js frontend and a FastAPI backend deployed as Python
              functions. The browser calls same-origin <code>/api/v1/*</code>, and Next.js rewrites
              it to the backend, so the backend URL and every API key stay server-side.
            </p>
            <ArchitectureDiagram />
          </DocSection>

          <DocSection id="data-flow" title="Data flow">
            <h3 className="text-lg font-semibold">Gap analysis (streamed over SSE)</h3>
            <p className="text-fg-muted max-w-3xl">
              <code>POST /sessions/{"{id}"}/analyze</code> returns a <code>text/event-stream</code>;
              the page fills in each section as its event arrives. A finished analysis is saved, and
              a second tab waits for the first run instead of paying for another.
            </p>
            <ol className="grid gap-3 md:grid-cols-2">
              {ANALYSIS_FLOW.map((s, i) => (
                <li key={s.title}>
                  <Card className="h-full space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="bg-accent-soft text-accent-soft-fg flex size-7 items-center justify-center rounded-full text-xs font-semibold">
                        {i + 1}
                      </span>
                      {s.calls && <Badge tone="accent">{s.calls}</Badge>}
                    </div>
                    <h4 className="font-semibold">{s.title}</h4>
                    <p className="text-fg-muted text-sm">{s.body}</p>
                  </Card>
                </li>
              ))}
            </ol>

            <h3 className="pt-4 text-lg font-semibold">One interview turn</h3>
            <Card tone="muted" className="space-y-4">
              <pre className="overflow-x-auto font-mono text-xs leading-relaxed sm:text-sm">
                <code>{`START -(start)--> plan_interview --> ask_question --> END
START -(answer)-> evaluate_answer --> decide_next -+-> ask_follow_up --> END
                                                   +-> ask_question  --> END
                                                   +-> finish        --> END`}</code>
              </pre>
              <ul className="text-fg-muted space-y-2 text-sm">
                <li>
                  <strong className="text-fg">Code decides what to ask:</strong> the question mix
                  (technical, project, gap probe, behavioral, role fit) is chosen in Python from the
                  gap analysis; one strong-model call phrases all six questions.
                </li>
                <li>
                  <strong className="text-fg">One fast-model call per answer:</strong> scores
                  against 1/3/5 rubric anchors, judges whether the answer was shallow, and phrases a
                  follow-up. <code>decide_next</code> is plain code: at most one follow-up per
                  question.
                </li>
                <li>
                  <strong className="text-fg">Load → run → save:</strong> serverless functions
                  forget everything, so each request restores the JSON state, advances exactly one
                  turn and writes it back. Scores are never sent to the browser mid-interview.
                </li>
              </ul>
            </Card>
          </DocSection>

          <DocSection id="decisions" title="Design decisions and tradeoffs">
            <div className="grid gap-4 xl:grid-cols-2">
              {DECISIONS.map((d) => (
                <Card key={d.title} as="article" className="space-y-3">
                  <h3 className="font-semibold">{d.title}</h3>
                  <p className="text-fg-muted text-sm">{d.why}</p>
                  <p className="bg-surface-sunken text-fg-muted rounded-lg px-3 py-2 text-sm">
                    <span className="text-fg font-medium">Tradeoff: </span>
                    {d.tradeoff}
                  </p>
                </Card>
              ))}
            </div>
          </DocSection>

          <DocSection id="numbers" title="Measured numbers">
            <p className="text-fg-muted max-w-3xl">
              From live runs against Groq, Gemini and Supabase during development (November 2026),
              recorded in the <TextLink href={docUrl("CHANGELOG.md")}>changelog</TextLink> and the{" "}
              <TextLink href={docUrl("docs/QA_REPORT.md")}>QA report</TextLink>. Free-tier
              infrastructure, so the running cost is $0.
            </p>
            <DataTable
              caption="Measured latency and quality numbers"
              head={["Metric", "Measured", "Target", "Notes"]}
              rows={NUMBERS}
            />
          </DocSection>

          <DocSection id="evals" title="Evaluation">
            <div className="flex flex-wrap items-center gap-3">
              <Badge tone="accent">Coming in Phase 8</Badge>
              <p className="text-fg-muted text-sm">
                Synthetic, fictional datasets and a runner that writes <code>evals/results.md</code>
                . Results will be published here.
              </p>
            </div>
            <DataTable
              caption="Planned evaluation suite"
              head={["Eval", "What is measured", "Target", "Result"]}
              rows={EVALS.map((r) => [...r, <span key="r">Pending</span>])}
            />
          </DocSection>

          <DocSection id="security" title="Security and privacy">
            <ul className="grid gap-3 md:grid-cols-2">
              {SECURITY.map((s) => (
                <li
                  key={s}
                  className="border-border bg-surface text-fg-muted rounded-xl border p-4 text-sm"
                >
                  {s}
                </li>
              ))}
            </ul>
            <p className="text-fg-muted">
              Threat model, controls and the open items:{" "}
              <TextLink href={docUrl("docs/SECURITY.md")}>docs/SECURITY.md</TextLink>. What we keep
              and for how long:{" "}
              <Link
                href="/privacy"
                className={cn(
                  "text-link rounded font-medium underline underline-offset-2 hover:no-underline",
                  focusRing,
                )}
              >
                privacy page
              </Link>
              .
            </p>
          </DocSection>
        </div>
      </Container>
    </main>
  );
}
