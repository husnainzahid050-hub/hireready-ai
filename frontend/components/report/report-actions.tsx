"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

import { formatDate } from "@/components/report/report-body";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox, Input, Label } from "@/components/ui/field";
import { ApiError, deleteSession, emailReport, setShareLink, subscribeReminders } from "@/lib/api";
import type { ReportResponse, ShareInfo } from "@/lib/types";

type Panel = "share" | "email" | null;

function message(e: unknown) {
  return e instanceof ApiError ? e.message : "Connection lost. Please try again.";
}

/** Expand every <details> while printing so the PDF holds the whole report. */
function usePrintExpand() {
  useEffect(() => {
    const opened: HTMLDetailsElement[] = [];
    const before = () => {
      document.querySelectorAll("details").forEach((d) => {
        if (!d.open) {
          d.open = true;
          opened.push(d);
        }
      });
    };
    const after = () => {
      opened.splice(0).forEach((d) => (d.open = false));
    };
    window.addEventListener("beforeprint", before);
    window.addEventListener("afterprint", after);
    return () => {
      window.removeEventListener("beforeprint", before);
      window.removeEventListener("afterprint", after);
    };
  }, []);
}

export function PrintExpander() {
  usePrintExpand();
  return null;
}

// ------------------------------------------------------------------ share

function SharePanel({
  sessionId,
  share,
  expiresAt,
  onChange,
}: {
  sessionId: string;
  share: ShareInfo;
  expiresAt: string | null;
  onChange: (s: ShareInfo) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const url =
    share.path && typeof window !== "undefined" ? `${window.location.origin}${share.path}` : "";

  async function run(action: "create" | "revoke") {
    setBusy(true);
    setError(null);
    setCopied(false);
    try {
      onChange(await setShareLink(sessionId, action));
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      setError("Couldn't copy automatically. Select the link and copy it.");
    }
  }

  return (
    <div className="space-y-3 text-sm">
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <p className="font-medium">The link shows</p>
          <p className="text-fg-muted">Scores, your answers, feedback and your 7-day plan.</p>
        </div>
        <div>
          <p className="font-medium">It never shows</p>
          <p className="text-fg-muted">
            Your CV text or your email. Emails or phone numbers you said aloud are masked.
          </p>
        </div>
      </div>
      {share.active && url ? (
        <div className="space-y-2">
          <Label htmlFor="share-url">Anyone with this link can view a read-only copy</Label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Input id="share-url" readOnly value={url} onFocus={(e) => e.currentTarget.select()} />
            <Button onClick={copy} disabled={busy}>
              {copied ? "Copied" : "Copy link"}
            </Button>
            <Button variant="secondary" onClick={() => run("revoke")} disabled={busy}>
              Revoke
            </Button>
          </div>
          <p className="text-fg-subtle text-xs" aria-live="polite">
            {copied ? "Link copied. " : ""}
            Works until you revoke it, delete your data
            {formatDate(expiresAt) ? ` or the session expires on ${formatDate(expiresAt)}` : ""}.
            Search engines are told not to index it.
          </p>
        </div>
      ) : (
        <Button onClick={() => run("create")} disabled={busy}>
          {busy ? "Creating…" : "Create share link"}
        </Button>
      )}
      {error && (
        <p role="alert" className="text-danger-fg">
          {error}
        </p>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ email

function EmailPanel({
  sessionId,
  emailedAt,
  onSent,
}: {
  sessionId: string;
  emailedAt: string | null;
  onSent: (at: string) => void;
}) {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<{ to: string; at: string } | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await emailReport(sessionId, email.trim() || null);
      setSent({ to: res.sent_to, at: res.emailed_at });
      onSent(res.emailed_at);
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  }

  const last = sent ?? (emailedAt ? { to: null, at: emailedAt } : null);
  return (
    <div className="space-y-4">
      <form onSubmit={submit} className="space-y-2 text-sm">
        <Label htmlFor="report-email">Email address</Label>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input
            id="report-email"
            type="email"
            autoComplete="email"
            maxLength={320}
            placeholder="Leave empty to use the one you gave at the start"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <Button type="submit" disabled={busy}>
            {busy ? "Sending…" : "Send"}
          </Button>
        </div>
        <p className="text-fg-subtle text-xs">
          You get a short summary: your band and score, the top 3 fixes and day 1 of your plan. Your
          answers and CV are never put in the email.
        </p>
        <p aria-live="polite" className="text-success-fg">
          {last && `Sent${last.to ? ` to ${last.to}` : ""} · ${formatDate(last.at, true) ?? ""}`}
        </p>
        {error && (
          <p role="alert" className="text-danger-fg">
            {error}
          </p>
        )}
      </form>
      <ReminderOptIn sessionId={sessionId} email={email.trim() || null} />
    </div>
  );
}

// ------------------------------------------------------------------ reminders (Phase 7)

/**
 * Separate, unticked opt-in for daily 7-day-plan emails (double opt-in: the server sends one
 * confirmation email; nothing daily goes out until the person clicks it). Uses the address typed
 * in the email panel above, or the one given at the start.
 */
function ReminderOptIn({ sessionId, email }: { sessionId: string; email: string | null }) {
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [result, setResult] = useState<"pending" | "exists" | null>(null);

  async function subscribe() {
    setBusy(true);
    setError(null);
    try {
      setResult((await subscribeReminders(sessionId, email)).status);
    } catch (e) {
      if (e instanceof ApiError && e.code === "reminders_not_configured") setUnavailable(true);
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  const locked = unavailable || result !== null;
  return (
    <fieldset className="border-border space-y-2 border-t pt-4 text-sm">
      <legend className="sr-only">Daily prep-plan reminders</legend>
      <div className="flex items-start gap-3">
        <Checkbox
          id="reminder-opt-in"
          checked={checked}
          disabled={locked || busy}
          onChange={(e) => setChecked(e.target.checked)}
          aria-describedby="reminder-hint"
          className="mt-0.5"
        />
        <div className="space-y-1">
          <Label htmlFor="reminder-opt-in" className="font-medium">
            Also send me a short daily reminder for each day of my 7-day plan
          </Label>
          <p id="reminder-hint" className="text-fg-subtle text-xs">
            Optional and separate from the report email. We&apos;ll send one confirmation email
            first; daily emails start only after you click the link in it, and every one has a
            one-click unsubscribe. Uses the address above, or the one you gave at the start.
          </p>
        </div>
      </div>
      {checked && !locked && (
        <Button size="sm" onClick={subscribe} disabled={busy} className="sm:ml-8">
          {busy ? "Setting up…" : "Set up reminders"}
        </Button>
      )}
      <p aria-live="polite" className="text-success-fg">
        {result === "pending" &&
          "Check your inbox: click the confirmation link to start your daily reminders."}
        {result === "exists" &&
          "Reminders are already set up for this session. If you haven't confirmed yet, look for the confirmation email."}
      </p>
      {error && (
        <p role="alert" className="text-danger-fg">
          {error}
        </p>
      )}
    </fieldset>
  );
}

// ------------------------------------------------------------------ delete

function DeleteDialog({ sessionId }: { sessionId: string }) {
  const router = useRouter();
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await deleteSession(sessionId);
      router.push("/deleted");
    } catch (e) {
      setError(message(e));
      setBusy(false);
    }
  }

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        className="text-danger-fg"
        onClick={() => ref.current?.showModal()}
      >
        Delete my data
      </Button>
      <dialog
        ref={ref}
        aria-labelledby={titleId}
        className="bg-surface text-fg border-border shadow-raised m-auto w-[min(32rem,calc(100%-2rem))] rounded-2xl border p-6 backdrop:bg-black/50"
      >
        <h2 id={titleId} className="text-lg font-semibold">
          Delete everything from this session?
        </h2>
        <p className="text-fg-muted mt-2 text-sm">This removes, right now and for good:</p>
        <ul className="text-fg-muted mt-2 list-disc space-y-1 pl-5 text-sm">
          <li>your CV text and the job description</li>
          <li>your answers, transcripts and scores</li>
          <li>this report and any share link (it stops working)</li>
          <li>reminders and usage counters</li>
        </ul>
        <p className="text-fg-subtle mt-2 text-xs">Audio was never stored.</p>
        {error && (
          <p role="alert" className="text-danger-fg mt-3 text-sm">
            {error}
          </p>
        )}
        <div className="mt-5 flex flex-wrap justify-end gap-2">
          {/* Cancel gets focus first: a destructive action is never the default. */}
          <Button
            variant="secondary"
            autoFocus
            onClick={() => ref.current?.close()}
            disabled={busy}
          >
            Cancel
          </Button>
          <button
            type="button"
            onClick={confirm}
            disabled={busy}
            className="bg-danger-solid focus-visible:outline-ring min-h-11 rounded-lg px-4 text-sm font-medium text-white hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-55"
          >
            {busy ? "Deleting…" : "Delete everything"}
          </button>
        </div>
      </dialog>
    </>
  );
}

// ------------------------------------------------------------------ bar

export function ReportActions({
  sessionId,
  meta,
  onMeta,
}: {
  sessionId: string;
  meta: ReportResponse;
  onMeta: (m: ReportResponse) => void;
}) {
  const [panel, setPanel] = useState<Panel>(null);
  usePrintExpand();
  const toggle = (p: Panel) => setPanel((cur) => (cur === p ? null : p));

  return (
    <div className="space-y-3 print:hidden">
      <div className="flex flex-wrap items-center gap-2" role="toolbar" aria-label="Report actions">
        <Button
          variant="secondary"
          size="sm"
          aria-expanded={panel === "share"}
          aria-controls="panel-share"
          onClick={() => toggle("share")}
        >
          {meta.share.active ? "Share link: on" : "Share"}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          aria-expanded={panel === "email"}
          aria-controls="panel-email"
          disabled={!meta.email_configured}
          title={meta.email_configured ? undefined : "Email isn't set up on this server yet"}
          onClick={() => toggle("email")}
        >
          Email me this report
        </Button>
        <Button variant="secondary" size="sm" onClick={() => window.print()}>
          Print / Save as PDF
        </Button>
        <DeleteDialog sessionId={sessionId} />
      </div>
      {!meta.email_configured && (
        <p className="text-fg-subtle text-xs">
          Email isn&apos;t set up on this server yet, so report emails and daily plan reminders are
          off. Use a share link or Save as PDF instead.
        </p>
      )}
      {panel === "share" && (
        <Card id="panel-share" tone="muted">
          <SharePanel
            sessionId={sessionId}
            share={meta.share}
            expiresAt={meta.expires_at}
            onChange={(share) => onMeta({ ...meta, share })}
          />
        </Card>
      )}
      {panel === "email" && meta.email_configured && (
        <Card id="panel-email" tone="muted">
          <EmailPanel
            sessionId={sessionId}
            emailedAt={meta.emailed_at}
            onSent={(at) => onMeta({ ...meta, emailed_at: at })}
          />
        </Card>
      )}
    </div>
  );
}
