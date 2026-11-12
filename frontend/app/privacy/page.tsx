import type { Metadata } from "next";
import Link from "next/link";

import { CONTACT_EMAIL, GITHUB_URL } from "@/components/site/config";
import { DataTable, DocSection, TextLink } from "@/components/site/prose";
import { Card } from "@/components/ui/card";
import { cn, focusRing } from "@/components/ui/cn";
import { Check, Shield } from "@/components/ui/icons";
import { Container } from "@/components/ui/section";

export const ensureStatic = "navigation";

export const metadata: Metadata = {
  title: "Privacy",
  description:
    "What HireReady AI collects, which AI providers process it, how long it is kept, and what is never stored.",
  alternates: { canonical: "/privacy" },
};

const LAST_UPDATED = "12 November 2026";

const SUMMARY = [
  "Audio is never stored. Voice answers are transcribed, then discarded.",
  "Guest sessions are deleted automatically 7 days after they are created.",
  "Only the text of your CV is kept, never the file.",
  "No account, no tracking cookies, no advertising or analytics scripts.",
  "CV text never appears in our logs: they contain IDs only.",
];

const COLLECTED: React.ReactNode[][] = [
  [
    "CV text",
    "Text extracted from your PDF/DOCX (up to 30,000 characters), split into chunks with embeddings for search",
    "Gap analysis and tailored questions",
  ],
  ["Job description", "The text you paste", "Gap analysis and questions"],
  [
    "Your choices",
    "Interview mode, level and type; your consent",
    "Running the interview you asked for",
  ],
  [
    "Analysis and interview",
    "Profiles, skill verdicts with quotes, questions, your answers (typed or transcribed) and their scores",
    "Showing results and your report",
  ],
  [
    "Email (optional)",
    "Only if you enter it, plus which of the two email options you ticked",
    "Sending your report (when you tick the box or click “Email me this report”)",
  ],
  [
    "Prep reminders (optional)",
    "Your email, the job title, the 7 plan days and a hashed single-purpose link token, kept separately from your session",
    "Sending one short prep email a day for 7 days, after you confirm by email",
  ],
  [
    "Technical data",
    "A hashed guest token, per-session usage counters, request IDs; your IP address, hashed, for per-IP rate limiting",
    "Security and abuse prevention",
  ],
];

const PROCESSORS: React.ReactNode[][] = [
  [
    "Groq",
    "Text generation (analysis, questions, scoring); speech-to-text for voice answers",
    <TextLink key="g" href="https://groq.com/privacy-policy/">
      Privacy policy
    </TextLink>,
  ],
  [
    "Google Gemini API",
    "Embeddings of your CV chunks; backup text generation when Groq is busy",
    <TextLink key="ge" href="https://ai.google.dev/gemini-api/terms">
      Gemini API terms
    </TextLink>,
  ],
  [
    "Supabase",
    "Postgres database that stores the data listed above (Row Level Security on every table)",
    <TextLink key="s" href="https://supabase.com/privacy">
      Privacy policy
    </TextLink>,
  ],
  [
    "Vercel",
    "Hosts the website and the API; keeps short-lived request logs",
    <TextLink key="v" href="https://vercel.com/legal/privacy-policy">
      Privacy policy
    </TextLink>,
  ],
  [
    "Resend",
    "Sends the emails you ask for (report and prep reminders); open and click tracking are off",
    <TextLink key="r" href="https://resend.com/legal/privacy-policy">
      Privacy policy
    </TextLink>,
  ],
  [
    "Cloudflare Turnstile",
    "Checks that a person, not a bot, starts a session (on the start page and the demo button)",
    <TextLink key="c" href="https://www.cloudflare.com/turnstile-privacy-policy/">
      Turnstile privacy addendum
    </TextLink>,
  ],
  [
    "Upstash",
    "Rate-limit counters keyed by a hash of your IP address (never the address itself)",
    <TextLink key="u" href="https://upstash.com/trust/privacy.pdf">
      Privacy policy
    </TextLink>,
  ],
];

export default function PrivacyPage() {
  return (
    <main className="py-12 sm:py-16">
      <Container size="narrow" className="space-y-14">
        <header className="space-y-4">
          <p className="text-link text-sm font-semibold tracking-wide uppercase">Privacy</p>
          <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
            Your CV, your answers, and what happens to them
          </h1>
          <p className="text-fg-muted text-lg">
            HireReady is a portfolio project that runs on free tiers. It collects only what it needs
            to give you feedback, and this page says exactly what that is.
          </p>
          <p className="text-fg-subtle text-sm">Last updated {LAST_UPDATED}</p>
        </header>

        <Card tone="muted" className="space-y-4">
          <div className="flex items-center gap-3">
            <span className="bg-success-soft text-success-fg flex size-10 items-center justify-center rounded-xl">
              <Shield />
            </span>
            <h2 className="text-lg font-semibold">The short version</h2>
          </div>
          <ul className="space-y-2.5">
            {SUMMARY.map((s) => (
              <li key={s} className="flex gap-2.5">
                <Check className="text-success-fg mt-0.5 size-5 shrink-0" />
                <span>{s}</span>
              </li>
            ))}
          </ul>
        </Card>

        <DocSection id="collected" title="What we collect">
          <DataTable
            caption="Data collected"
            head={["Data", "What exactly", "Why"]}
            rows={COLLECTED}
          />
          <p className="text-fg-muted">
            Uploaded files are parsed in memory and thrown away; only the extracted text is saved.
            Your session is reachable only with a random guest key kept in your browser&apos;s local
            storage, which is why a session link doesn&apos;t open on another device.
          </p>
        </DocSection>

        <DocSection id="processors" title="Who processes it">
          <p className="text-fg-muted">
            To generate feedback, parts of your CV, the job description and your answers are sent to
            these services. Each one handles them under its own terms.
          </p>
          <DataTable
            caption="Service providers"
            head={["Provider", "What it does for us", "Their terms"]}
            rows={PROCESSORS}
          />
          <p className="border-warning-solid/30 bg-warning-soft text-warning-fg rounded-xl border p-4 text-sm">
            We use the free tiers of these services. Free-tier terms can allow a provider to use
            submitted content to improve its services (Google&apos;s Gemini API terms say so for
            unpaid use). Please leave out anything you would not want shared, such as your home
            address or ID numbers; they are not needed for the analysis.
          </p>
          <p className="text-fg-muted">
            When you ask for your report by email, our email provider (Resend) receives your email
            address and a short summary of the report (scores, top fixes, day 1 of your plan; never
            your answers or CV text). Prep reminders send one plan day at a time. We send nothing
            you didn&apos;t ask for, never add you to any other list, and send no reminder until you
            confirm from the first email.
          </p>
        </DocSection>

        <DocSection id="retention" title="How long we keep it">
          <ul className="text-fg-muted list-disc space-y-2 pl-5">
            <li>
              <strong className="text-fg">Audio:</strong> never stored. A recording is sent for
              transcription and discarded; only the text transcript is kept.
            </li>
            <li>
              <strong className="text-fg">Guest sessions:</strong> expire 7 days after creation.
              From then on the API refuses every request for them, so the data can no longer be
              opened by anyone, including you.
            </li>
            <li>
              <strong className="text-fg">Deletion:</strong> a cleanup job runs every night (about
              02:00 UTC) and deletes expired sessions with everything in them: CV text, analysis,
              questions, answers, report and share link. So data is gone at most about a day after
              it expires. You don&apos;t have to wait: the &ldquo;Delete my data&rdquo; button on
              your report deletes the session and everything in it at once, and any share link stops
              working.
            </li>
            <li id="reminders">
              <strong className="text-fg">Prep reminders:</strong> only if you tick &ldquo;Send me 7
              daily prep emails&rdquo; and then confirm from the first email (if you don&apos;t, the
              request is deleted after 3 days). They are kept apart from your session so a plan can
              finish after the session is deleted, and they stop on their own after day 7 (or pause
              after 3 days without a &ldquo;Mark done&rdquo;). Unsubscribing in one click, or
              &ldquo;Delete my data&rdquo;, deletes your email and plan at once; otherwise they are
              deleted 3 days after the last email. No tracking pixels.
            </li>
            <li>
              <strong className="text-fg">Logs:</strong> record IDs, timings and error types, never
              CV text. Email addresses are masked by the log formatter.
            </li>
          </ul>
        </DocSection>

        <DocSection id="not-collected" title="What we don't do">
          <ul className="text-fg-muted list-disc space-y-2 pl-5">
            <li>No accounts, passwords or social logins.</li>
            <li>No advertising, analytics or tracking scripts, and no cookies for tracking.</li>
            <li>We don&apos;t sell or share your data with anyone beyond the providers above.</li>
            <li>
              Shared report links leave out your CV text and your email, mask any email address or
              phone number you said in an answer, are hidden from search engines, and stop working
              when you revoke them, delete your data or the session expires.
            </li>
          </ul>
        </DocSection>

        <DocSection id="contact" title="Contact">
          <p className="text-fg-muted">
            {CONTACT_EMAIL ? (
              <>
                Questions or deletion requests:{" "}
                <TextLink href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</TextLink>.
              </>
            ) : (
              <>
                Questions or deletion requests: open an issue on{" "}
                <TextLink href={`${GITHUB_URL}/issues`}>GitHub</TextLink> (don&apos;t include
                personal data there; we will reply with a private channel). Security problems: use
                GitHub&apos;s private vulnerability reporting, as described in{" "}
                <TextLink href={`${GITHUB_URL}/blob/main/docs/SECURITY.md`}>SECURITY.md</TextLink>.
              </>
            )}
          </p>
          <p className="text-fg-muted">
            Curious how this is enforced in code? See the{" "}
            <Link
              href="/engineering#security"
              className={cn(
                "text-link rounded font-medium underline underline-offset-2 hover:no-underline",
                focusRing,
              )}
            >
              engineering page
            </Link>
            .
          </p>
        </DocSection>
      </Container>
    </main>
  );
}
