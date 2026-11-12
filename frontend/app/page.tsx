import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import { DemoButton } from "@/components/demo-button";
import { ProductPreview } from "@/components/landing/product-preview";
import { TAGLINE } from "@/components/site/config";
import { Badge } from "@/components/ui/badge";
import { ButtonLink } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn, focusRing } from "@/components/ui/cn";
import {
  ArrowRight,
  Calendar,
  Chart,
  Check,
  FileText,
  MessageQuestion,
  Mic,
  Quote,
  Scan,
  Share,
  Shield,
  Upload,
} from "@/components/ui/icons";
import { Container, SectionHeading } from "@/components/ui/section";

// The landing page must stay fully prerendered (SPEC 8.1): the build fails if anything here
// starts reading request data.
export const ensureStatic = "navigation";

export const metadata: Metadata = {
  alternates: { canonical: "/" },
};

type Status = "live" | "progress" | "soon";
const STATUS: Record<Status, { label: string; tone: "success" | "accent" | "neutral" }> = {
  live: { label: "Live", tone: "success" },
  progress: { label: "In progress", tone: "accent" },
  soon: { label: "Coming soon", tone: "neutral" },
};

// Flip a status here when a phase ships (voice = Phase 4, report/email/share = Phase 5).
const FEATURES: { icon: ReactNode; title: string; body: string; status: Status }[] = [
  {
    icon: <Quote />,
    title: "Gap analysis with verified quotes",
    body: "Every required skill is marked strong, weak or missing. Evidence is a real quote from your CV, checked word for word in code, or an honest “no evidence found”.",
    status: "live",
  },
  {
    icon: <MessageQuestion />,
    title: "Questions this role will ask",
    body: "Likely interview questions grouped by topic, built from the job description, your own projects and a curated rubric for 14 competencies.",
    status: "live",
  },
  {
    icon: <Calendar />,
    title: "A 7-day prep plan",
    body: "Daily tasks that target your gaps first, linking only to hand-picked learning resources, never invented URLs.",
    status: "live",
  },
  {
    icon: <FileText />,
    title: "Mock interview with follow-ups",
    body: "About 6 questions tailored to your CV and the job. If an answer is shallow, the interviewer digs deeper, like a real one. Answer by voice or by typing.",
    status: "live",
  },
  {
    icon: <Mic />,
    title: "Voice answers and speech metrics",
    body: "Answer out loud; questions are read aloud with captions. Practice mode shows your speaking pace, filler words and long pauses. Audio is transcribed, then discarded.",
    status: "live",
  },
  {
    icon: <Share />,
    title: "Scored report, email and share link",
    body: "Per-question scores with reasons, an improved sample answer, a read-only share link and a printable PDF.",
    status: "soon",
  },
];

const STEPS = [
  {
    icon: <Upload />,
    title: "Upload",
    body: "Your CV (PDF or DOCX) and the job description you copied.",
  },
  {
    icon: <Scan />,
    title: "Analyze",
    body: "Match score, skill gaps with quotes, likely questions and a 7-day plan, streamed in about 20 seconds.",
  },
  {
    icon: <Mic />,
    title: "Interview",
    body: "An AI interviewer asks about 6 tailored questions and follows up on shallow answers.",
  },
  {
    icon: <Chart />,
    title: "Report",
    body: "Scores, what the interviewer was looking for, and a better sample answer.",
    soon: true,
  },
];

const PROOF = [
  { value: "100%", label: "of evidence quotes verbatim in the CV across QA runs" },
  { value: "~0.5 s", label: "until the first analysis result appears" },
  { value: "17–22 s", label: "for a complete analysis of the sample CV" },
  { value: "3–4", label: "LLM calls per analysis, so it stays fast on free tiers" },
];

// Trust strip under the hero CTAs. Only claims that are true on main.
// TODO(final): "Data expires in 7 days" -> "Auto-deletes in 7 days" once the Phase 7 cleanup cron
// is live (until then expired sessions are refused by the API but not yet physically deleted).
const TRUST = [
  "Free",
  "No sign-up",
  "Audio never stored",
  "Data expires in 7 days",
  "Practice only",
];

// "Shows its working": the three things competitors don't show. Keep each one checkable.
const WORKING: { icon: ReactNode; title: string; body: ReactNode; detail: ReactNode }[] = [
  {
    icon: <Quote />,
    title: "Quotes, verified in code",
    body: "Every skill verdict quotes your CV. Code then checks the quote really is in your CV; if it isn't, the skill says “no evidence found”.",
    detail: (
      <figure className="border-success-solid/20 bg-success-soft rounded-xl border p-3 text-sm">
        <blockquote className="text-fg">
          “Built a RAG assistant in Python and FastAPI that answers support tickets”
        </blockquote>
        <figcaption className="text-success-fg mt-2 flex items-center gap-1.5 font-medium">
          <Check className="size-4" /> Found word for word in the CV
        </figcaption>
      </figure>
    ),
  },
  {
    icon: <Chart />,
    title: "Scores with their maths",
    body: "The model gives verdicts and feedback; the number is computed in code from a published formula, and the page shows each part of the sum.",
    detail: (
      <details className="border-border bg-surface-muted rounded-xl border p-3 text-sm">
        <summary className={cn("text-fg cursor-pointer rounded font-medium", focusRing)}>
          How is the match score calculated?
        </summary>
        <p className="text-fg-muted mt-2 font-mono text-xs leading-relaxed">
          100 × (0.7 × must-have + 0.2 × nice-to-have + 0.1 × seniority fit), where strong evidence
          = 1, weak = 0.5, none = 0
        </p>
      </details>
    ),
  },
  {
    icon: <Scan />,
    title: "Measured, not claimed",
    // TODO(final): once Phase 8 evals are on main, say "Eval results are published" and link
    // /engineering#evals with the headline number from evals/results.json.
    body: "Latency and quality are measured on live runs, and the Engineering page explains how each number was taken, including the slow paths.",
    detail: (
      <Link
        href="/engineering#numbers"
        className={cn(
          "text-link inline-flex items-center gap-1.5 rounded text-sm font-medium hover:underline",
          focusRing,
        )}
      >
        See the measured numbers <ArrowRight className="size-4" />
      </Link>
    ),
  },
];

const STACK = [
  "Next.js 16",
  "React 19",
  "TypeScript",
  "Tailwind CSS",
  "FastAPI",
  "Pydantic",
  "LangGraph",
  "Groq",
  "Google Gemini",
  "Supabase + pgvector",
  "Vercel",
];

const FAQ: { q: string; a: ReactNode }[] = [
  {
    q: "Is it really free?",
    a: "Yes. There is no sign-up and no payment. The project runs entirely on free tiers, so there are fair-use limits per session.",
  },
  {
    q: "What happens to my CV?",
    a: (
      <>
        Only the extracted text is kept, never the file. It is linked to a guest session that only
        your browser can open, and the session expires after 7 days. Details are on the{" "}
        <Link href="/privacy" className="text-link font-medium underline underline-offset-2">
          privacy page
        </Link>
        .
      </>
    ),
  },
  {
    q: "How is the match score calculated?",
    a: "With a published formula, not by the AI: 70% must-have skills, 20% nice-to-have skills and 10% seniority fit, where strong evidence counts 1, weak evidence 0.5 and no evidence 0. The analysis page shows each part.",
  },
  {
    q: "Can the AI make up evidence?",
    a: "It can try, but it won't get through. The model must quote your CV, and code then checks that the quote really appears in it. If it doesn't, the skill is marked “no evidence”.",
  },
  {
    q: "Do I need a microphone?",
    a: "No. You can do the whole interview in text mode. Voice mode uses your microphone only while you are recording an answer, and the recording is discarded after transcription.",
  },
  {
    q: "Can I use it during a real interview?",
    a: "No, and we won't build that. HireReady is for practice before the interview: it never listens to a live interview and never suggests answers in real time. The point is that you can answer on your own.",
  },
  {
    q: "Which jobs does it work for?",
    a: "Any job description you paste (200 to 8,000 characters). Its interview rubric is strongest for tech roles: software, data and AI engineering at junior and mid level.",
  },
];

function StatusBadge({ status }: { status: Status }) {
  const s = STATUS[status];
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

export default function Home() {
  return (
    <main>
      {/* ------------------------------------------------------------ hero */}
      <section
        aria-labelledby="hero-title"
        className="border-border relative isolate overflow-hidden border-b"
      >
        <div
          aria-hidden
          className="absolute inset-0 -z-10 bg-[radial-gradient(70%_55%_at_15%_0%,color-mix(in_srgb,var(--accent)_10%,transparent),transparent)]"
        />
        <Container className="grid items-center gap-12 py-14 sm:py-20 lg:grid-cols-[1.1fr_1fr] lg:gap-16 lg:py-24">
          <div className="space-y-7">
            <Badge tone="accent" className="px-3 py-1">
              A mock interview that shows its working
            </Badge>
            <h1
              id="hero-title"
              className="text-4xl leading-[1.1] font-semibold tracking-tight text-balance sm:text-5xl lg:text-[3.4rem]"
            >
              {TAGLINE}
            </h1>
            <p className="text-fg-muted max-w-xl text-lg text-pretty">
              HireReady checks your CV against one specific job and interviews you on it. Every
              verdict comes with a quote from your CV, checked word for word, and every score comes
              with the formula behind it.
            </p>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
              <ButtonLink href="/start" size="lg">
                Start free mock interview <ArrowRight className="size-4" />
              </ButtonLink>
              <DemoButton />
            </div>
            <ul
              aria-label="At a glance"
              className="text-fg-muted flex flex-wrap gap-x-5 gap-y-2 text-sm"
            >
              {TRUST.map((t) => (
                <li key={t} className="flex items-center gap-1.5">
                  <Check className="text-success-fg size-4" />
                  {t}
                </li>
              ))}
            </ul>
          </div>
          <ProductPreview />
        </Container>
      </section>

      {/* ------------------------------------------------------------ proof */}
      <section aria-label="Measured results" className="border-border bg-surface-muted border-b">
        <Container>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-8 py-10 lg:grid-cols-4">
            {PROOF.map((p) => (
              <div key={p.value} className="flex flex-col-reverse gap-1">
                <dt className="text-fg-muted text-sm">{p.label}</dt>
                <dd className="text-2xl font-semibold tracking-tight tabular-nums sm:text-3xl">
                  {p.value}
                </dd>
              </div>
            ))}
          </dl>
        </Container>
      </section>

      {/* ------------------------------------------------------------ shows its working */}
      <section
        aria-labelledby="shows-its-working"
        className="border-border border-b py-16 sm:py-24"
      >
        <Container className="space-y-12">
          <SectionHeading
            id="shows-its-working"
            eyebrow="Why trust it"
            title="Feedback that shows its working"
          >
            Most AI interview tools give you a score with no &ldquo;why&rdquo;. HireReady shows the
            evidence and the maths, so you can check every piece of feedback yourself.
          </SectionHeading>
          <ul className="grid gap-4 lg:grid-cols-3">
            {WORKING.map((w) => (
              <li key={w.title}>
                <Card className="flex h-full flex-col gap-3">
                  <span className="bg-accent-soft text-accent-soft-fg flex size-10 items-center justify-center rounded-xl">
                    {w.icon}
                  </span>
                  <h3 className="text-base font-semibold">{w.title}</h3>
                  <p className="text-fg-muted text-sm">{w.body}</p>
                  <div className="mt-auto pt-2">{w.detail}</div>
                </Card>
              </li>
            ))}
          </ul>
        </Container>
      </section>

      {/* ------------------------------------------------------------ how it works */}
      <section aria-labelledby="how-it-works" className="py-16 sm:py-24">
        <Container className="space-y-12">
          <SectionHeading id="how-it-works" eyebrow="How it works" title="From job post to ready">
            Four steps, from the job post you copied to knowing what to say and what to fix.
          </SectionHeading>
          <ol className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {STEPS.map((s, i) => (
              <li key={s.title}>
                <Card className="h-full space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="bg-accent-soft text-accent-soft-fg flex size-10 items-center justify-center rounded-xl">
                      {s.icon}
                    </span>
                    <span className="text-fg-subtle text-sm font-medium tabular-nums">
                      Step {i + 1}
                    </span>
                  </div>
                  <h3 className="flex flex-wrap items-center gap-2 text-lg font-semibold">
                    {s.title}
                    {s.soon && <StatusBadge status="soon" />}
                  </h3>
                  <p className="text-fg-muted text-sm">{s.body}</p>
                </Card>
              </li>
            ))}
          </ol>
        </Container>
      </section>

      {/* ------------------------------------------------------------ features */}
      <section
        aria-labelledby="features"
        className="border-border bg-surface-muted border-y py-16 sm:py-24"
      >
        <Container className="space-y-12">
          <SectionHeading id="features" eyebrow="Features" title="Feedback you can check">
            Generic prep sites ask generic questions. HireReady works from your CV and this job, and
            shows its evidence.
          </SectionHeading>
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((f) => (
              <li key={f.title}>
                <Card className="h-full space-y-3">
                  <div className="flex items-start justify-between gap-3">
                    <span className="bg-accent-soft text-accent-soft-fg flex size-10 items-center justify-center rounded-xl">
                      {f.icon}
                    </span>
                    <StatusBadge status={f.status} />
                  </div>
                  <h3 className="text-base font-semibold">{f.title}</h3>
                  <p className="text-fg-muted text-sm">{f.body}</p>
                </Card>
              </li>
            ))}
          </ul>
        </Container>
      </section>

      {/* ------------------------------------------------------------ built with + privacy */}
      <section aria-labelledby="built-with" className="py-16 sm:py-24">
        <Container className="grid gap-6 lg:grid-cols-2">
          <Card className="space-y-5">
            <h2 id="built-with" className="text-xl font-semibold tracking-tight">
              Built with
            </h2>
            <ul className="flex flex-wrap gap-2">
              {STACK.map((s) => (
                <li
                  key={s}
                  className="border-border bg-surface-muted text-fg-muted rounded-lg border px-3 py-1.5 text-sm"
                >
                  {s}
                </li>
              ))}
            </ul>
            <p className="text-fg-muted text-sm">
              Hybrid search with rank fusion, a stateless LangGraph interviewer, and quotes and
              scores checked in code rather than trusted from the model.
            </p>
            <Link
              href="/engineering"
              className={cn(
                "text-link inline-flex items-center gap-1.5 rounded text-sm font-medium hover:underline",
                focusRing,
              )}
            >
              Read how it&apos;s engineered <ArrowRight className="size-4" />
            </Link>
          </Card>

          <Card className="space-y-5">
            <div className="flex items-center gap-3">
              <span className="bg-success-soft text-success-fg flex size-10 items-center justify-center rounded-xl">
                <Shield />
              </span>
              <h2 className="text-xl font-semibold tracking-tight">Private by default</h2>
            </div>
            {/* TODO(final): "Guest data auto-deletes in 7 days." once the Phase 7 cleanup cron is live. */}
            <p className="text-lg font-medium text-pretty">
              Audio is never stored. Guest data expires after 7 days.
            </p>
            <ul className="text-fg-muted space-y-2 text-sm">
              {[
                "No account: a random guest key in your browser is the only way into your session.",
                "Only the text of your CV is kept, never the file, and it never appears in our logs.",
                "Shared with AI providers only to generate your feedback; the privacy page lists them.",
              ].map((t) => (
                <li key={t} className="flex gap-2">
                  <Check className="text-success-fg mt-0.5 size-4 shrink-0" />
                  {t}
                </li>
              ))}
            </ul>
            <Link
              href="/privacy"
              className={cn(
                "text-link inline-flex items-center gap-1.5 rounded text-sm font-medium hover:underline",
                focusRing,
              )}
            >
              Read the privacy page <ArrowRight className="size-4" />
            </Link>
          </Card>
        </Container>
      </section>

      {/* ------------------------------------------------------------ FAQ */}
      <section aria-labelledby="faq" className="border-border border-t py-16 sm:py-24">
        <Container size="narrow" className="space-y-10">
          <SectionHeading id="faq" eyebrow="FAQ" title="Questions, answered" align="center" />
          <div className="divide-border border-border bg-surface divide-y rounded-2xl border">
            {FAQ.map((f) => (
              <details key={f.q} className="group px-5 sm:px-6">
                <summary
                  className={cn(
                    "flex cursor-pointer list-none items-center justify-between gap-4 rounded py-5 font-medium [&::-webkit-details-marker]:hidden",
                    focusRing,
                  )}
                >
                  {f.q}
                  <span
                    aria-hidden
                    className="bg-surface-sunken text-fg-muted flex size-6 shrink-0 items-center justify-center rounded-full transition-transform group-open:rotate-45"
                  >
                    +
                  </span>
                </summary>
                <p className="text-fg-muted pb-5">{f.a}</p>
              </details>
            ))}
          </div>
        </Container>
      </section>

      {/* ------------------------------------------------------------ final CTA */}
      <section aria-labelledby="cta" className="pb-20">
        <Container>
          <div className="bg-accent text-accent-fg relative isolate overflow-hidden rounded-3xl px-6 py-12 text-center sm:px-12">
            <div
              aria-hidden
              className="absolute inset-0 -z-10 bg-[radial-gradient(50%_80%_at_50%_0%,rgb(255_255_255/0.18),transparent)]"
            />
            <h2 id="cta" className="text-2xl font-semibold tracking-tight text-balance sm:text-3xl">
              Your next interview is for one specific job. Practise for that one.
            </h2>
            <p className="mx-auto mt-3 max-w-xl text-indigo-100">
              Free, no sign-up, and a sample CV if you just want to look around.
            </p>
            <div className="mt-8 flex flex-col justify-center gap-3 sm:flex-row">
              <ButtonLink
                href="/start"
                size="lg"
                variant="secondary"
                className="border-transparent bg-white text-indigo-700 hover:bg-indigo-50 focus-visible:outline-white"
              >
                Start free mock interview <ArrowRight className="size-4" />
              </ButtonLink>
            </div>
          </div>
        </Container>
      </section>
    </main>
  );
}
