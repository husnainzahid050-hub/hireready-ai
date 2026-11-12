"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { AnswerComposer } from "@/components/interview/answer-composer";
import {
  FeedbackCard,
  InterviewerPanel,
  InterviewSkeleton,
  Notice,
  ProgressHeader,
} from "@/components/interview/parts";
import { Transcript } from "@/components/interview/transcript";
import { ModeSwitch } from "@/components/interview/voice/mode-switch";
import { Badge } from "@/components/ui/badge";
import { Button, ButtonLink } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn, focusRing } from "@/components/ui/cn";
import { ArrowRight, Check } from "@/components/ui/icons";
import { Spinner } from "@/components/ui/notice";
import { SpeechFeedback } from "@/components/interview/voice/speech-feedback";
import { VoiceControls } from "@/components/interview/voice/voice-controls";
import { ApiError, getInterview, getToken, startInterview, submitAnswer } from "@/lib/api";
import { type AnswerMode, getSessionMode, saveSessionMode } from "@/lib/prefs";
import type { InterviewTurn, Question, SpeechMetrics } from "@/lib/types";
import { type Recording, RECORDER_ERROR_TEXT, recordingSupport } from "@/lib/use-recorder";
import { useSpeech } from "@/lib/use-speech";
import { submitVoiceAnswer } from "@/lib/voice";

// The recorder (MediaRecorder + Web Audio) is only needed in voice mode: load it on demand.
const VoiceRecorder = dynamic(
  () => import("@/components/interview/voice/voice-recorder").then((m) => m.VoiceRecorder),
  {
    ssr: false,
    loading: () => (
      <div
        aria-hidden
        className="bg-surface-sunken h-80 animate-pulse rounded-2xl motion-reduce:animate-none"
      />
    ),
  },
);

/** Voice when the session was created in voice mode and this browser can record; else text. */
function defaultMode(sessionId: string): AnswerMode {
  const chosen = getSessionMode(sessionId);
  return chosen === "voice" && recordingSupport() === null ? "voice" : "text";
}

const VOICE_RETRY_CODES = new Set(["stt_unavailable", "ai_unavailable"]);

type Phase = "loading" | "no_session" | "not_started" | "not_analyzed" | "load_error" | "ready";

/** An error while sending an answer. The draft is never cleared on error. */
type SendError = { kind: "retry" | "rate" | "generic"; message: string };

const NETWORK_MESSAGE = "We couldn't reach the server. Check your connection and try again.";
const DRAFT_KEY = (id: string) => `hireready:draft:${id}`;

function describe(q: Question, total: number): string {
  return `Question ${q.order} of about ${total}${q.is_follow_up ? ", follow-up" : ""}: ${q.text}`;
}

function answeredSummary(history: InterviewTurn["history"]): string {
  const follow = history.filter((h) => h.question.is_follow_up).length;
  const main = history.length - follow;
  const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;
  return `You answered ${plural(main, "question")}${follow ? ` and ${plural(follow, "follow-up")}` : ""}.`;
}

function waitText(seconds: number | null): string {
  if (seconds === null) return "Please wait a minute, then try again.";
  if (seconds < 60)
    return `Please wait ${seconds} second${seconds === 1 ? "" : "s"}, then try again.`;
  const m = Math.ceil(seconds / 60);
  return `Please wait about ${m} minute${m === 1 ? "" : "s"}, then try again.`;
}

// Drafts survive a reload (sessionStorage: this tab only, cleared when it closes).
function loadDraft(sessionId: string, questionId: string): string {
  try {
    const raw = sessionStorage.getItem(DRAFT_KEY(sessionId));
    if (!raw) return "";
    const d = JSON.parse(raw) as { q: string; t: string };
    return d.q === questionId ? d.t : "";
  } catch {
    return "";
  }
}

function saveDraft(sessionId: string, questionId: string, text: string) {
  try {
    if (text)
      sessionStorage.setItem(DRAFT_KEY(sessionId), JSON.stringify({ q: questionId, t: text }));
    else sessionStorage.removeItem(DRAFT_KEY(sessionId));
  } catch {
    /* storage full or disabled: drafts are a nice-to-have */
  }
}

export function InterviewView({ sessionId }: { sessionId: string }) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [turn, setTurn] = useState<InterviewTurn | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [pending, setPending] = useState<{ question: Question; answer_text: string } | null>(null);
  const [sendError, setSendError] = useState<SendError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  // Rate limiting: a deadline plus a ticking clock (kept in state so render stays pure).
  const [waitUntil, setWaitUntil] = useState<number | null>(null);
  const [now, setNow] = useState(0);
  // Start screen
  const [practice, setPractice] = useState(false);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<SendError | null>(null);

  // Voice (Phase 4)
  const [mode, setMode] = useState<AnswerMode>("text");
  const [voiceUnavailable, setVoiceUnavailable] = useState<string | null>(null);
  const [failedRecording, setFailedRecording] = useState<Recording | null>(null);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [lastMetrics, setLastMetrics] = useState<SpeechMetrics | null>(null);
  const speech = useSpeech();
  const spokenFor = useRef<string | null>(null);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const recordButtonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  /** Show a new turn: restore its draft, announce the question, move focus to the answer box. */
  const applyTurn = useCallback(
    (t: InterviewTurn, opts: { announce: boolean }) => {
      setTurn(t);
      setPhase("ready");
      if (t.question) setDraft(loadDraft(sessionId, t.question.id));
      if (opts.announce) {
        setAnnouncement(
          t.status === "completed"
            ? "Interview complete."
            : t.question
              ? describe(t.question, t.progress.total_planned)
              : "",
        );
        requestAnimationFrame(() => {
          const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
          panelRef.current?.scrollIntoView({
            block: "start",
            behavior: reduce ? "auto" : "smooth",
          });
          (textareaRef.current ?? recordButtonRef.current)?.focus({ preventScroll: true });
        });
      }
    },
    [sessionId],
  );

  const handleFatal = useCallback((e: unknown): boolean => {
    if (e instanceof ApiError && (e.code === "session_not_found" || e.status === 404)) {
      setPhase("no_session");
      return true;
    }
    if (e instanceof ApiError && e.code === "not_analyzed") {
      setPhase("not_analyzed");
      return true;
    }
    return false;
  }, []);

  // Initial load / resume after reload.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!getToken(sessionId)) {
        setPhase("no_session");
        return;
      }
      const unsupported = recordingSupport();
      setVoiceUnavailable(unsupported ? RECORDER_ERROR_TEXT[unsupported] : null);
      setMode(defaultMode(sessionId));
      try {
        const t = await getInterview(sessionId);
        if (!cancelled) applyTurn(t, { announce: false });
      } catch (e) {
        if (cancelled) return;
        if (e instanceof ApiError && e.code === "not_started") setPhase("not_started");
        else if (!handleFatal(e)) {
          setLoadError(e instanceof ApiError ? e.message : NETWORK_MESSAGE);
          setPhase("load_error");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, applyTurn, handleFatal]);

  // Rate-limit countdown.
  useEffect(() => {
    if (waitUntil === null) return;
    const id = window.setInterval(() => {
      const t = Date.now();
      setNow(t);
      if (t >= waitUntil) {
        setWaitUntil(null);
        setSendError((err) => (err?.kind === "rate" ? null : err));
        setStartError((err) => (err?.kind === "rate" ? null : err));
      }
    }, 1000);
    return () => window.clearInterval(id);
  }, [waitUntil]);

  // Read each new question aloud in voice mode (captions are always on screen).
  const currentQuestion = phase === "ready" ? (turn?.question ?? null) : null;
  const { speak } = speech;
  useEffect(() => {
    if (mode !== "voice" || !currentQuestion || spokenFor.current === currentQuestion.id) return;
    spokenFor.current = currentQuestion.id;
    speak(currentQuestion.text);
  }, [mode, currentQuestion, speak]);

  function changeMode(m: AnswerMode) {
    setMode(m);
    saveSessionMode(sessionId, m);
    setFailedRecording(null);
    if (m === "text") speech.cancel();
    requestAnimationFrame(() =>
      (m === "text" ? textareaRef.current : recordButtonRef.current)?.focus(),
    );
  }

  function rateLimited(e: ApiError): SendError {
    const t = Date.now();
    setNow(t);
    setWaitUntil(t + (e.retryAfter ?? 30) * 1000);
    return {
      kind: "rate",
      message: `You're going a little fast. ${waitText(e.retryAfter)} Your answer is safe.`,
    };
  }

  async function start() {
    setStarting(true);
    setStartError(null);
    try {
      applyTurn(await startInterview(sessionId, practice), { announce: true });
    } catch (e) {
      if (handleFatal(e)) return;
      if (e instanceof ApiError && e.status === 429) setStartError(rateLimited(e));
      else if (e instanceof ApiError && e.status < 500)
        setStartError({ kind: "generic", message: e.message });
      else
        setStartError({
          kind: "retry",
          message:
            e instanceof ApiError && e.code === "ai_unavailable"
              ? "The AI interviewer is busy right now. Please try again in a moment."
              : e instanceof ApiError
                ? e.message
                : NETWORK_MESSAGE,
        });
    } finally {
      setStarting(false);
    }
  }

  /** Re-sync with the server (after wrong_question / interview_completed). */
  async function refetch(text: string) {
    try {
      const t = await getInterview(sessionId);
      // If the server already has this exact answer (e.g. the response was lost), drop the draft.
      const alreadySaved = t.history.some((h) => h.answer_text.trim() === text);
      if (alreadySaved && turn?.question) saveDraft(sessionId, turn.question.id, "");
      applyTurn(t, { announce: true });
      if (!alreadySaved && t.question) {
        // Keep the unsent text so nothing is lost; the user decides whether to reuse it.
        setDraft(text);
        saveDraft(sessionId, t.question.id, text);
      }
      setNotice(
        alreadySaved
          ? "Your answer was already received. Here's the next question."
          : "The interview had moved on (perhaps in another tab), so we loaded the latest question. Your text is still in the box.",
      );
    } catch (e) {
      if (!handleFatal(e)) setSendError({ kind: "retry", message: NETWORK_MESSAGE });
    }
  }

  async function send() {
    const q = turn?.question;
    const text = draft.trim();
    if (!q || !text || sending) return;
    setSending(true);
    setSendError(null);
    setNotice(null);
    setPending({ question: q, answer_text: text });
    setAnnouncement("Answer sent. The interviewer is thinking…");
    try {
      const next = await submitAnswer(sessionId, q.id, text);
      saveDraft(sessionId, q.id, "");
      setPending(null);
      setLastMetrics(null);
      // The answer endpoint returns `history: []` (only GET sends the full list), so keep the
      // transcript client-side by appending the answer the server just accepted.
      const history = next.history.length
        ? next.history
        : [
            ...(turn?.history ?? []),
            { question: q, answer_text: next.last_answer?.transcript ?? text },
          ];
      applyTurn({ ...next, history }, { announce: true });
    } catch (e) {
      setPending(null);
      setAnnouncement("");
      if (handleFatal(e)) return;
      if (e instanceof ApiError) {
        if (e.code === "wrong_question" || e.code === "interview_completed") await refetch(text);
        else if (e.status === 429) setSendError(rateLimited(e));
        else if (e.code === "ai_unavailable" || e.status >= 500)
          setSendError({
            kind: "retry",
            message:
              "The AI interviewer is temporarily unavailable. Your answer is still here; try sending it again in a moment.",
          });
        else setSendError({ kind: "generic", message: e.message });
      } else {
        setSendError({ kind: "retry", message: `${NETWORK_MESSAGE} Your answer is still here.` });
      }
      textareaRef.current?.focus({ preventScroll: true });
    } finally {
      setSending(false);
    }
  }

  /** Upload a recorded answer. On failure the recording is kept for "Retry upload". */
  async function sendVoice(rec: Recording) {
    const q = turn?.question;
    if (!q || sending) return;
    speech.cancel();
    setSending(true);
    setSendError(null);
    setNotice(null);
    setFailedRecording(null);
    setUploadProgress(0);
    setPending({ question: q, answer_text: "(voice answer, transcribing…)" });
    setAnnouncement("Uploading your answer…");
    try {
      const next = await submitVoiceAnswer(sessionId, q.id, rec, (p) => {
        setUploadProgress(p);
        if (p >= 1) setAnnouncement("Transcribing your answer…");
      });
      setPending(null);
      setLastMetrics(next.last_answer?.speech_metrics ?? null);
      const history = next.history.length
        ? next.history
        : [
            ...(turn?.history ?? []),
            { question: q, answer_text: next.last_answer?.transcript ?? "" },
          ];
      applyTurn({ ...next, history }, { announce: true });
    } catch (e) {
      setPending(null);
      setAnnouncement("");
      if (handleFatal(e)) return;
      if (
        e instanceof ApiError &&
        (e.code === "wrong_question" || e.code === "interview_completed")
      ) {
        try {
          applyTurn(await getInterview(sessionId), { announce: true });
          setNotice(
            "The interview had moved on (perhaps in another tab), so we loaded the latest question.",
          );
        } catch (err) {
          if (!handleFatal(err)) setSendError({ kind: "retry", message: NETWORK_MESSAGE });
        }
        return;
      }
      setFailedRecording(rec);
      if (e instanceof ApiError && e.status === 429) setSendError(rateLimited(e));
      else if (e instanceof ApiError && (VOICE_RETRY_CODES.has(e.code) || e.status >= 500))
        setSendError({
          kind: "retry",
          message:
            e.code === "stt_unavailable"
              ? e.message
              : "The AI interviewer is temporarily unavailable. Your recording is kept here; try uploading it again in a moment.",
        });
      else if (e instanceof ApiError) setSendError({ kind: "generic", message: e.message });
      else
        setSendError({
          kind: "retry",
          message: NETWORK_MESSAGE + " Your recording is kept here.",
        });
      requestAnimationFrame(() => recordButtonRef.current?.focus({ preventScroll: true }));
    } finally {
      setSending(false);
      setUploadProgress(null);
    }
  }

  function onDraftChange(v: string) {
    setDraft(v);
    if (turn?.question) saveDraft(sessionId, turn.question.id, v);
  }

  const waitSeconds = waitUntil === null ? null : Math.max(0, Math.ceil((waitUntil - now) / 1000));

  // ------------------------------------------------------------------ non-interview states

  if (phase === "loading") return <InterviewSkeleton />;

  if (phase === "no_session") {
    return (
      <Notice tone="warning">
        This session belongs to another browser, or it was cleared or has expired. For privacy,
        sessions can only be opened on the device that created them.
        <div>
          <ButtonLink href="/start" variant="secondary" size="sm" className="mt-3">
            Start a new one
          </ButtonLink>
        </div>
      </Notice>
    );
  }

  if (phase === "not_analyzed") {
    return (
      <Notice tone="info">
        Your CV analysis needs to finish before the interview can start.
        <div>
          <ButtonLink
            href={`/session/${sessionId}/analysis`}
            variant="secondary"
            size="sm"
            className="mt-3"
          >
            Go to your analysis
          </ButtonLink>
        </div>
      </Notice>
    );
  }

  if (phase === "load_error") {
    return (
      <Notice tone="error">
        <p className="font-medium">{loadError}</p>
        <Button
          variant="secondary"
          size="sm"
          className="mt-3"
          onClick={() => window.location.reload()}
        >
          Try again
        </Button>
      </Notice>
    );
  }

  if (phase === "not_started") {
    return (
      <div className="mx-auto max-w-2xl space-y-6">
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
            Ready for your mock interview?
          </h1>
          <p className="text-fg-muted text-pretty">
            About 6 questions tailored to your CV and this job: technical, a project deep-dive, a
            skill check, behavioral and role fit. The interviewer may ask a follow-up when an answer
            is brief. There is no timer, so take your time.
          </p>
        </header>

        <Card>
          <fieldset className="min-w-0 space-y-3">
            <legend className="text-fg-muted mb-3 text-sm font-medium">Interview style</legend>
            <label className="flex cursor-pointer items-start justify-between gap-4">
              <span className="space-y-1">
                <span className="block font-medium">Practice mode</span>
                <span id="practice-desc" className="text-fg-muted block text-sm">
                  <strong className="font-medium">Off</strong>: realistic, like a real interview;
                  your scores appear only in the report at the end.{" "}
                  <strong className="font-medium">On</strong>: brief feedback and a tip after each
                  answer.
                </span>
              </span>
              <input
                type="checkbox"
                role="switch"
                checked={practice}
                onChange={(e) => setPractice(e.target.checked)}
                aria-describedby="practice-desc"
                className="peer sr-only"
              />
              <span
                aria-hidden
                className="bg-fg-subtle peer-checked:bg-accent peer-focus-visible:outline-ring relative mt-1 inline-flex h-7 w-12 shrink-0 items-center rounded-full transition-colors peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 motion-reduce:transition-none peer-checked:[&>span]:translate-x-5"
              >
                <span className="ml-1 size-5 rounded-full bg-white shadow transition-transform motion-reduce:transition-none" />
              </span>
            </label>
            <p className="text-fg flex items-center gap-1.5 text-sm" aria-live="polite">
              {practice
                ? "Practice mode on: you'll see brief feedback after each answer."
                : "Realistic mode: no feedback until the end."}
            </p>
          </fieldset>
        </Card>

        {startError && (
          <Notice tone={startError.kind === "rate" ? "warning" : "error"}>
            <p>
              {startError.kind === "rate"
                ? `Too many requests. ${waitText(waitSeconds)}`
                : startError.message}
            </p>
          </Notice>
        )}

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <Button
            size="lg"
            onClick={start}
            disabled={starting || waitUntil !== null}
            className="w-full sm:w-auto"
          >
            {starting ? (
              <>
                <Spinner />
                Preparing your questions…
              </>
            ) : startError?.kind === "retry" ? (
              "Try again"
            ) : (
              <>
                Start interview
                <ArrowRight className="size-4" />
              </>
            )}
          </Button>
          <p className="text-fg-subtle text-sm">
            Answer by voice or by typing; you can switch at any time.
          </p>
        </div>
        <p className="text-fg-muted text-sm">
          <Link
            href={`/session/${sessionId}/analysis`}
            className={cn("rounded underline hover:no-underline", focusRing)}
          >
            Back to your analysis
          </Link>
        </p>
      </div>
    );
  }

  // ------------------------------------------------------------------ interview (phase "ready")

  if (!turn) return <InterviewSkeleton />;
  const completed = turn.status === "completed";
  const feedback = turn.practice_mode ? (turn.last_answer?.feedback ?? null) : null;

  const liveRegion = (
    <div className="sr-only" aria-live="polite" aria-atomic="true">
      {announcement}
    </div>
  );

  if (completed || !turn.question) {
    return (
      <div className="space-y-6">
        {liveRegion}
        <ProgressHeader question={null} total={turn.progress.total_planned} completed />
        <Card as="section" tone="raised" className="space-y-3">
          <span className="bg-success-soft text-success-fg flex size-10 items-center justify-center rounded-full">
            <Check className="size-5" strokeWidth={2.5} />
          </span>
          <h1 className="text-2xl font-semibold tracking-tight">Interview complete. Nice work!</h1>
          <p className="text-fg-muted">
            {answeredSummary(turn.history)} Your scored report is ready to build: per-answer scores
            with quotes from what you said, improved example answers, an overall readiness score and
            a fresh 7-day plan.
          </p>
          <div className="flex flex-col gap-2 pt-1 sm:flex-row sm:flex-wrap">
            <ButtonLink href={`/session/${sessionId}/report`} className="w-full sm:w-auto">
              See your report
              <ArrowRight className="size-4" />
            </ButtonLink>
            <ButtonLink
              href={`/session/${sessionId}/analysis`}
              variant="secondary"
              className="w-full sm:w-auto"
            >
              Back to your analysis
            </ButtonLink>
          </div>
        </Card>
        {feedback && <FeedbackCard feedback={feedback} />}
        <Transcript history={turn.history} pending={null} defaultOpen />
      </div>
    );
  }

  const question = turn.question;
  return (
    <div className="space-y-6">
      {liveRegion}
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Mock interview</h1>
        <Badge tone={turn.practice_mode ? "accent" : "neutral"}>
          {turn.practice_mode ? "Practice mode: feedback after each answer" : "Realistic mode"}
        </Badge>
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0 space-y-5">
          <div ref={panelRef} className="scroll-mt-4 space-y-5">
            <ProgressHeader
              question={question}
              total={turn.progress.total_planned}
              completed={false}
            />
            {feedback && !sending && <FeedbackCard feedback={feedback} />}
            {turn.practice_mode && lastMetrics && !sending && (
              <SpeechFeedback metrics={lastMetrics} />
            )}
            <InterviewerPanel
              question={question}
              status={speech.speaking ? "speaking" : sending ? "thinking" : "listening"}
              controls={
                speech.supported ? (
                  <VoiceControls
                    muted={speech.muted}
                    speaking={speech.speaking}
                    onToggleMute={() => speech.setMuted(!speech.muted)}
                    onReplay={() => speech.speak(question.text, { force: true })}
                  />
                ) : undefined
              }
            />
          </div>

          {notice && <Notice tone="info">{notice}</Notice>}
          {sendError && (
            <Notice tone={sendError.kind === "rate" ? "warning" : "error"}>
              <p>
                {sendError.kind === "rate"
                  ? `You're going a little fast. ${waitText(waitSeconds)} Your answer is safe.`
                  : sendError.message}
              </p>
              {sendError.kind === "retry" && (
                <Button
                  variant="secondary"
                  onClick={() => {
                    if (mode === "voice" && failedRecording) void sendVoice(failedRecording);
                    else void send();
                  }}
                  disabled={sending}
                  className="mt-3"
                >
                  {mode === "voice" && failedRecording ? "Retry upload" : "Retry sending answer"}
                </Button>
              )}
            </Notice>
          )}

          <ModeSwitch
            mode={mode}
            onChange={changeMode}
            voiceUnavailable={voiceUnavailable}
            disabled={sending}
          />
          {mode === "voice" ? (
            <VoiceRecorder
              key={question.id}
              onRecorded={(r) => void sendVoice(r)}
              onRecordStart={speech.cancel}
              onRetry={() => {
                if (failedRecording) void sendVoice(failedRecording);
              }}
              onDiscardFailed={() => {
                setFailedRecording(null);
                setSendError(null);
              }}
              onSwitchToText={() => changeMode("text")}
              onAnnounce={setAnnouncement}
              sending={sending}
              uploadProgress={uploadProgress}
              failedRecording={failedRecording}
              blockedReason={waitSeconds !== null ? `Wait ${waitSeconds}s` : null}
              buttonRef={recordButtonRef}
            />
          ) : (
            <AnswerComposer
              value={draft}
              onChange={onDraftChange}
              onSubmit={send}
              sending={sending}
              blockedReason={waitSeconds !== null ? `Wait ${waitSeconds}s` : null}
              textareaRef={textareaRef}
            />
          )}
        </div>

        <aside
          aria-label="Interview transcript"
          className="lg:sticky lg:top-6 lg:max-h-[calc(100vh-3rem)] lg:self-start lg:overflow-y-auto"
        >
          <Transcript history={turn.history} pending={pending} />
        </aside>
      </div>
    </div>
  );
}
