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
    body: "About 6 questions tailored to your CV and the job. If an answer is shallow, the interviewer digs deeper, like a real one. Text mode is live.",
    status: "live",
  },
  {
    icon: <Mic />,
    title: "Voice answers and speech metrics",
    body: "Answer out loud and see your speaking pace, filler words and long pauses. Audio is transcribed, then discarded.",
    status: "progress",
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
        Only the extracted text is kept, never the file. It is linked to a guest session that
        only your browser can open, and the session expires after 7 days. Details are on the{" "}
        <Link href="/privacy" className="font-medium text-link underline underline-offset-2">
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
    a: "No. You can do the whole interview in text mode. Voice mode, when it is available, uses your microphone only while you are answering.",
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
        className="relative isolate overflow-hidden border-b border-border"
      >
        <div
          aria-hidden
          className="absolute inset-0 -z-10 bg-[radial-gradient(70%_55%_at_15%_0%,color-mix(in_srgb,var(--accent)_10%,transparent),transparent)]"
        />
        <Container className="grid items-center gap-12 py-14 sm:py-20 lg:grid-cols-[1.1fr_1fr] lg:gap-16 lg:py-24">
          <div className="space-y-7">
            <Badge tone="accent" className="px-3 py-1">
              Free AI interview prep · no sign-up
            </Badge>
            <h1
              id="hero-title"
              className="text-4xl leading-[1.1] font-semibold tracking-tight text-balance sm:text-5xl lg:text-[3.4rem]"
            >
              {TAGLINE}
            </h1>
            <p className="max-w-xl text-lg text-pretty text-fg-muted">
              HireReady compares your CV with one specific job, shows which required skills you can
              prove (with quotes from your CV), and then interviews you on exactly those.
            </p>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
              <ButtonLink href="/start" size="lg">
                Start free mock interview <ArrowRight className="size-4" />
              </ButtonLink>
              <DemoButton />
            </div>
            <ul className="flex flex-wrap gap-x-5 gap-y-2 text-sm text-fg-muted">
              {["Results in about 20 seconds", "Audio is never stored", "Data expires in 7 days"].map(
                (t) => (
                  <li key={t} className="flex items-center gap-1.5">
                    <Check className="size-4 text-success-fg" />
                    {t}
                  </li>
                ),
              )}
            </ul>
          </div>
          <ProductPreview />
        </Container>
      </section>

      {/* ------------------------------------------------------------ proof */}
      <section aria-label="Measured results" className="border-b border-border bg-surface-muted">
        <Container>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-8 py-10 lg:grid-cols-4">
            {PROOF.map((p) => (
              <div key={p.value} className="space-y-1">
                <dt className="sr-only">{p.label}</dt>
                <dd className="text-2xl font-semibold tracking-tight tabular-nums sm:text-3xl">
                  {p.value}
                </dd>
                <dd className="text-sm text-fg-muted">{p.label}</dd>
              </div>
            ))}
          </dl>
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
                    <span className="flex size-10 items-center justify-center rounded-xl bg-accent-soft text-accent-soft-fg">
                      {s.icon}
                    </span>
                    <span className="text-sm font-medium text-fg-subtle tabular-nums">
                      Step {i + 1}
                    </span>
                  </div>
                  <h3 className="flex flex-wrap items-center gap-2 text-lg font-semibold">
                    {s.title}
                    {s.soon && <StatusBadge status="soon" />}
                  </h3>
                  <p className="text-sm text-fg-muted">{s.body}</p>
                </Card>
              </li>
            ))}
          </ol>
        </Container>
      </section>

      {/* ------------------------------------------------------------ features */}
      <section
        aria-labelledby="features"
        className="border-y border-border bg-surface-muted py-16 sm:py-24"
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
                    <span className="flex size-10 items-center justify-center rounded-xl bg-accent-soft text-accent-soft-fg">
                      {f.icon}
                    </span>
                    <StatusBadge status={f.status} />
                  </div>
                  <h3 className="text-base font-semibold">{f.title}</h3>
                  <p className="text-sm text-fg-muted">{f.body}</p>
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
                  className="rounded-lg border border-border bg-surface-muted px-3 py-1.5 text-sm text-fg-muted"
                >
                  {s}
                </li>
              ))}
            </ul>
            <p className="text-sm text-fg-muted">
              Hybrid search with rank fusion, a stateless LangGraph interviewer, and quotes and
              scores checked in code rather than trusted from the model.
            </p>
            <Link
              href="/engineering"
              className={cn(
                "inline-flex items-center gap-1.5 rounded text-sm font-medium text-link hover:underline",
                focusRing,
              )}
            >
              Read how it&apos;s engineered <ArrowRight className="size-4" />
            </Link>
          </Card>

          <Card className="space-y-5">
            <div className="flex items-center gap-3">
              <span className="flex size-10 items-center justify-center rounded-xl bg-success-soft text-success-fg">
                <Shield />
              </span>
              <h2 className="text-xl font-semibold tracking-tight">Private by default</h2>
            </div>
            <p className="text-lg font-medium text-pretty">
              Audio is never stored. Guest data auto-deletes in 7 days.
            </p>
            <ul className="space-y-2 text-sm text-fg-muted">
              {[
                "No account: a random guest key in your browser is the only way into your session.",
                "Only the text of your CV is kept, never the file, and it never appears in our logs.",
                "Shared with AI providers only to generate your feedback; the privacy page lists them.",
              ].map((t) => (
                <li key={t} className="flex gap-2">
                  <Check className="mt-0.5 size-4 shrink-0 text-success-fg" />
                  {t}
                </li>
              ))}
            </ul>
            <Link
              href="/privacy"
              className={cn(
                "inline-flex items-center gap-1.5 rounded text-sm font-medium text-link hover:underline",
                focusRing,
              )}
            >
              Read the privacy page <ArrowRight className="size-4" />
            </Link>
          </Card>
        </Container>
      </section>

      {/* ------------------------------------------------------------ FAQ */}
      <section aria-labelledby="faq" className="border-t border-border py-16 sm:py-24">
        <Container size="narrow" className="space-y-10">
          <SectionHeading id="faq" eyebrow="FAQ" title="Questions, answered" align="center" />
          <div className="divide-y divide-border rounded-2xl border border-border bg-surface">
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
                    className="flex size-6 shrink-0 items-center justify-center rounded-full bg-surface-sunken text-fg-muted transition-transform group-open:rotate-45"
                  >
                    +
                  </span>
                </summary>
                <p className="pb-5 text-fg-muted">{f.a}</p>
              </details>
            ))}
          </div>
        </Container>
      </section>

      {/* ------------------------------------------------------------ final CTA */}
      <section aria-labelledby="cta" className="pb-20">
        <Container>
          <div className="relative isolate overflow-hidden rounded-3xl bg-accent px-6 py-12 text-center text-accent-fg sm:px-12">
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
