"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState, type ReactNode } from "react";

import { Button, buttonClasses } from "@/components/ui/button";
import { cn, focusRing } from "@/components/ui/cn";
import { Checkbox, FieldError, Hint, Input, Label, Textarea } from "@/components/ui/field";
import { Alert, Check, FileText, Upload, X } from "@/components/ui/icons";
import { ApiError, createSession, uploadDocuments } from "@/lib/api";
import { getTurnstileToken, TURNSTILE_FAILED_MESSAGE, turnstileEnabled } from "@/lib/turnstile";
import type { SessionOptions } from "@/lib/types";

const MAX_BYTES = 2 * 1024 * 1024;
const JD_MIN = 200;
const JD_MAX = 8000;
const ACCEPT =
  ".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

function validateFile(f: File): string | null {
  const name = f.name.toLowerCase();
  if (!name.endsWith(".pdf") && !name.endsWith(".docx")) return "Please upload a PDF or DOCX file.";
  if (f.size > MAX_BYTES) return "Your CV must be 2 MB or smaller.";
  if (f.size === 0) return "That file is empty.";
  return null;
}

function formatSize(bytes: number): string {
  return bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

type Option<T extends string> = { value: T; label: string; hint?: string };

function Segmented<T extends string>({
  label,
  name,
  value,
  options,
  onChange,
}: {
  label: string;
  name: string;
  value: T;
  options: Option<T>[];
  onChange: (v: T) => void;
}) {
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium">{label}</legend>
      <div className="flex flex-wrap gap-2">
        {options.map((o) => {
          const active = value === o.value;
          return (
            <label
              key={o.value}
              className={cn(
                "flex min-h-11 cursor-pointer items-center gap-1.5 rounded-lg border px-3.5 text-sm font-medium transition-colors",
                "has-[:focus-visible]:outline-ring has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2",
                active
                  ? "border-accent bg-accent-soft text-accent-soft-fg"
                  : "border-border-strong bg-surface text-fg-muted hover:bg-surface-sunken hover:text-fg",
              )}
            >
              <input
                type="radio"
                className="sr-only"
                name={name}
                value={o.value}
                checked={active}
                onChange={() => onChange(o.value)}
              />
              {active && <Check className="size-4" />}
              {o.label}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

/** A numbered form section: keeps the long form scannable. */
function Step({
  n,
  title,
  description,
  children,
}: {
  n: number;
  title: string;
  description?: ReactNode;
  children: ReactNode;
}) {
  const id = `step-${n}`;
  return (
    <section aria-labelledby={id} className="grid gap-4 sm:grid-cols-[2.25rem_1fr]">
      <span
        aria-hidden
        className="bg-accent-soft text-accent-soft-fg hidden size-9 items-center justify-center rounded-full text-sm font-semibold sm:flex"
      >
        {n}
      </span>
      <div className="min-w-0 space-y-4">
        <div className="space-y-1">
          <h2 id={id} className="text-lg font-semibold tracking-tight">
            <span className="text-fg-subtle sm:hidden">{n}. </span>
            {title}
          </h2>
          {description && <p className="text-fg-muted text-sm">{description}</p>}
        </div>
        {children}
      </div>
    </section>
  );
}

export function StartForm() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [jd, setJd] = useState("");
  const [opts, setOpts] = useState<SessionOptions>({
    mode: "voice",
    difficulty: "junior",
    interview_type: "mixed",
    email: null,
    email_opt_in: false,
    reminders_opt_in: false,
    consent: false,
  });
  // Cloudflare Turnstile renders here when a session is created (off without a site key).
  const challenge = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [attempted, setAttempted] = useState(false);
  // The session created by a failed attempt (e.g. a scanned PDF) is reused on retry instead of
  // leaving an orphan session behind each time. A change of options needs a new session.
  const created = useRef<{ id: string; options: string } | null>(null);

  const jdLen = jd.trim().length;
  const fileError = file ? validateFile(file) : null;
  const jdTooShort = jdLen > 0 && jdLen < JD_MIN;
  const jdTooLong = jdLen > JD_MAX;
  const canSubmit =
    !!file && !fileError && jdLen >= JD_MIN && jdLen <= JD_MAX && opts.consent && !busy;

  // What is still missing, shown under the submit button instead of a silently disabled button.
  const missing = [
    !file || fileError ? "your CV" : null,
    jdLen < JD_MIN || jdTooLong ? "the job description" : null,
    !opts.consent ? "your consent" : null,
  ].filter(Boolean) as string[];

  function pick(f: File | undefined | null) {
    if (!f) return;
    setFile(f);
    setError(null); // validation errors for the file are shown by the dropzone itself
  }

  function clearFile() {
    setFile(null);
    if (inputRef.current) inputRef.current.value = "";
    inputRef.current?.focus();
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setAttempted(true);
    if (!canSubmit || !file) return;
    setBusy(true);
    setError(null);
    try {
      const options = { ...opts, email: opts.email?.trim() || null };
      const key = JSON.stringify(options);
      if (created.current?.options !== key) {
        let token: string | null = null;
        if (turnstileEnabled && challenge.current) {
          try {
            token = await getTurnstileToken(challenge.current, "always");
          } catch {
            setError(TURNSTILE_FAILED_MESSAGE);
            setBusy(false);
            return;
          }
        }
        const { session_id } = await createSession(options, false, token);
        created.current = { id: session_id, options: key };
      }
      const session_id = created.current.id;
      await uploadDocuments(session_id, file, jd);
      router.push(`/session/${session_id}/analysis`);
    } catch (err) {
      // Out of uploads for this session, or it is gone: the next attempt starts a fresh one.
      if (err instanceof ApiError && (err.code === "quota_exceeded" || err.status === 404)) {
        created.current = null;
      }
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      setBusy(false);
    }
  }

  const dropState = fileError ? "error" : dragging ? "drag" : file ? "chosen" : "idle";

  return (
    <form onSubmit={submit} className="space-y-10" noValidate aria-busy={busy}>
      {/* ------------------------------------------------------------ 1. CV */}
      <Step
        n={1}
        title="Your CV"
        description="PDF or DOCX, up to 2 MB and 5 pages. Text-based files work best (not scans)."
      >
        <input
          ref={inputRef}
          id="cv"
          type="file"
          accept={ACCEPT}
          className="peer sr-only"
          aria-describedby="cv-help"
          aria-invalid={!!fileError || undefined}
          onChange={(e) => pick(e.target.files?.[0])}
        />
        <label
          htmlFor="cv"
          onDragEnter={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={(e) => {
            // Ignore leave events fired when moving over child elements.
            if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
          }}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            pick(e.dataTransfer.files[0]);
          }}
          className={cn(
            "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed px-6 py-9 text-center transition-colors",
            "peer-focus-visible:outline-ring peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2",
            dropState === "idle" &&
              "border-border-strong bg-surface-muted hover:border-fg-subtle hover:bg-surface-sunken",
            dropState === "drag" && "border-accent bg-accent-soft",
            dropState === "chosen" && "border-success-solid/60 bg-success-soft",
            dropState === "error" && "border-danger-solid/70 bg-danger-soft",
          )}
        >
          {file ? (
            <>
              <span
                className={cn(
                  "flex size-12 items-center justify-center rounded-xl",
                  fileError ? "bg-surface text-danger-fg" : "bg-surface text-success-fg",
                )}
              >
                {fileError ? <Alert className="size-6" /> : <FileText className="size-6" />}
              </span>
              <span className="max-w-full space-y-0.5">
                <span className="block truncate font-medium">
                  {dragging ? "Drop to replace your file" : file.name}
                </span>
                <span className="text-fg-muted block text-sm">
                  {formatSize(file.size)} · {fileError ? "not accepted" : "ready"} ·{" "}
                  <span className="text-link font-medium underline underline-offset-2">
                    {fileError ? "choose another file" : "click to replace"}
                  </span>
                </span>
              </span>
            </>
          ) : (
            <>
              <span
                className={cn(
                  "bg-surface shadow-card flex size-12 items-center justify-center rounded-xl",
                  dragging ? "text-accent-soft-fg" : "text-fg-muted",
                )}
              >
                <Upload className="size-6" />
              </span>
              <span className="space-y-0.5">
                <span className="block font-medium">
                  {dragging ? "Drop it here" : "Drop your CV here, or click to browse"}
                </span>
                <span className="text-fg-muted block text-sm">PDF or DOCX · max 2 MB</span>
              </span>
            </>
          )}
        </label>
        <p id="cv-help" className="sr-only">
          PDF or DOCX, up to 2 megabytes and 5 pages.
        </p>
        {file && (
          <div className="flex justify-end">
            <Button variant="ghost" size="sm" onClick={clearFile}>
              <X className="size-4" /> Remove file
            </Button>
          </div>
        )}
        {fileError ? (
          <FieldError>{fileError}</FieldError>
        ) : (
          attempted && !file && <FieldError>Add your CV to continue.</FieldError>
        )}
      </Step>

      {/* ------------------------------------------------------------ 2. JD */}
      <Step
        n={2}
        title="The job description"
        description="Paste the full posting: title, responsibilities and requirements. More detail gives better questions."
      >
        <div className="space-y-2">
          <Label htmlFor="jd" className="sr-only">
            Job description
          </Label>
          <Textarea
            id="jd"
            value={jd}
            onChange={(e) => setJd(e.target.value)}
            rows={10}
            maxLength={JD_MAX + 500}
            placeholder={
              "Junior AI Engineer at …\n\nResponsibilities\n• …\n\nRequirements\n• Python, SQL …"
            }
            aria-describedby="jd-count"
            aria-invalid={jdTooLong || (attempted && jdLen < JD_MIN) || undefined}
            className="min-h-56 resize-y"
          />
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <span
              className={cn(
                jdTooShort || jdTooLong || (attempted && jdLen === 0)
                  ? "text-danger-fg"
                  : "text-fg-subtle",
              )}
            >
              {jdTooLong
                ? `Too long by ${(jdLen - JD_MAX).toLocaleString()} characters. Trim the "about us" part.`
                : jdTooShort
                  ? `${(JD_MIN - jdLen).toLocaleString()} more characters needed`
                  : jdLen === 0
                    ? `At least ${JD_MIN} characters`
                    : "Looks good"}
            </span>
            <span
              id="jd-count"
              className={cn(
                "tabular-nums",
                jdTooShort || jdTooLong ? "text-danger-fg" : "text-fg-subtle",
              )}
            >
              {jdLen.toLocaleString()} / {JD_MAX.toLocaleString()} characters
              {jdTooShort ? ` (at least ${JD_MIN})` : ""}
            </span>
          </div>
        </div>
      </Step>

      {/* ------------------------------------------------------------ 3. options */}
      <Step
        n={3}
        title="Interview settings"
        description="You can always run another session with different settings."
      >
        <div className="border-border bg-surface grid gap-6 rounded-2xl border p-5 sm:grid-cols-2">
          <Segmented
            label="Interview mode"
            name="mode"
            value={opts.mode}
            onChange={(mode) => setOpts({ ...opts, mode })}
            options={[
              { value: "voice", label: "Voice" },
              { value: "text", label: "Text" },
            ]}
          />
          <Segmented
            label="Level"
            name="difficulty"
            value={opts.difficulty}
            onChange={(difficulty) => setOpts({ ...opts, difficulty })}
            options={[
              { value: "junior", label: "Junior" },
              { value: "mid", label: "Mid" },
            ]}
          />
          <div className="sm:col-span-2">
            <Segmented
              label="Interview type"
              name="interview_type"
              value={opts.interview_type}
              onChange={(interview_type) => setOpts({ ...opts, interview_type })}
              options={[
                { value: "mixed", label: "Mixed" },
                { value: "technical", label: "Technical" },
                { value: "behavioral", label: "Behavioral" },
              ]}
            />
          </div>
        </div>
      </Step>

      {/* ------------------------------------------------------------ 4. email + consent */}
      <Step n={4} title="Report and consent">
        <div className="space-y-3">
          <Label htmlFor="email">
            Email <Hint>(optional, only for the emails you tick below)</Hint>
          </Label>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            inputMode="email"
            placeholder="you@example.com"
            value={opts.email ?? ""}
            onChange={(e) =>
              setOpts({
                ...opts,
                email: e.target.value,
                email_opt_in: e.target.value ? opts.email_opt_in : false,
                reminders_opt_in: e.target.value ? opts.reminders_opt_in : false,
              })
            }
            className="sm:max-w-sm"
          />
          {/* Two separate, unticked consents: one email vs a 7-day series (ICO guidance). */}
          <fieldset className="space-y-2" disabled={!opts.email}>
            <legend className="sr-only">Email options</legend>
            <label
              className={cn(
                "flex items-start gap-3 text-sm",
                opts.email ? "cursor-pointer" : "text-fg-subtle",
              )}
            >
              <Checkbox
                className="mt-0.5"
                checked={opts.email_opt_in}
                onChange={(e) => setOpts({ ...opts, email_opt_in: e.target.checked })}
              />
              <span>Email me my report when it&apos;s ready (one email)</span>
            </label>
            <label
              className={cn(
                "flex items-start gap-3 text-sm",
                opts.email ? "cursor-pointer" : "text-fg-subtle",
              )}
            >
              <Checkbox
                className="mt-0.5"
                checked={opts.reminders_opt_in}
                onChange={(e) => setOpts({ ...opts, reminders_opt_in: e.target.checked })}
              />
              <span>
                Send me 7 daily prep emails after the interview, then they stop.
                <span className="text-fg-muted block">
                  We email you once to confirm first. Unsubscribe in one click.
                </span>
              </span>
            </label>
          </fieldset>
        </div>

        <label
          className={cn(
            "flex cursor-pointer items-start gap-3 rounded-2xl border p-4 text-sm transition-colors",
            opts.consent
              ? "border-accent/40 bg-accent-soft/60"
              : attempted
                ? "border-danger-solid/60 bg-surface"
                : "border-border bg-surface hover:bg-surface-muted",
          )}
        >
          <Checkbox
            className="mt-0.5"
            checked={opts.consent}
            aria-describedby="consent-privacy"
            onChange={(e) => setOpts({ ...opts, consent: e.target.checked })}
          />
          <span className="space-y-1">
            <span className="text-fg block font-medium">
              I agree that my CV and answers are processed by AI services to generate feedback.
            </span>
            <span id="consent-privacy" className="text-fg-muted block">
              Audio is never stored, and guest sessions expire after 7 days.{" "}
              <Link
                href="/privacy"
                target="_blank"
                className={cn(
                  "text-link rounded font-medium underline underline-offset-2",
                  focusRing,
                )}
              >
                Read the privacy page
                <span className="sr-only"> (opens in a new tab)</span>
              </Link>
            </span>
          </span>
        </label>
      </Step>

      {/* ------------------------------------------------------------ submit */}
      <div className="border-border space-y-3 border-t pt-8 sm:pl-[3.25rem]">
        {turnstileEnabled && <div ref={challenge} className="min-h-0" />}
        {error && (
          <div
            role="alert"
            className="border-danger-solid/30 bg-danger-soft text-danger-fg flex gap-3 rounded-xl border p-4 text-sm"
          >
            <Alert className="mt-0.5 size-5 shrink-0" />
            <p>{error}</p>
          </div>
        )}
        <button
          type="submit"
          aria-disabled={!canSubmit}
          disabled={busy}
          className={buttonClasses({
            size: "lg",
            className: cn("w-full sm:w-auto", !canSubmit && !busy && "opacity-60"),
          })}
        >
          {busy && (
            <span
              aria-hidden
              className="size-4 animate-spin rounded-full border-2 border-current border-r-transparent"
            />
          )}
          {busy ? "Uploading…" : "Analyze my CV"}
        </button>
        <p className="text-fg-muted text-sm" aria-live="polite">
          {busy
            ? "Checking your file. The analysis starts on the next page."
            : missing.length
              ? `To continue, add ${missing.join(", ").replace(/, ([^,]*)$/, " and $1")}.`
              : "Takes about 20 seconds. Results appear as they are ready."}
        </p>
      </div>
    </form>
  );
}
