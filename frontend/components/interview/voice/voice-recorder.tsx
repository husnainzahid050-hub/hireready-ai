"use client";

import { useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";
import { cn, focusRing } from "@/components/ui/cn";
import { Mic } from "@/components/ui/icons";
import {
  formatClock,
  type Recording,
  RECORDER_ERROR_TEXT,
  type RecorderError,
  useRecorder,
} from "@/lib/use-recorder";

const ACCENT_PILL = "bg-accent-soft text-accent-soft-fg ring-accent/20";
const WARN_PILL = "bg-warning-soft text-warning-fg ring-warning-solid/25";
const PILL: Record<string, { text: string; cls: string }> = {
  idle: { text: "Ready", cls: "bg-surface-sunken text-fg-muted ring-border" },
  requesting: { text: "Waiting for mic", cls: ACCENT_PILL },
  recording: { text: "Recording", cls: "bg-danger-soft text-danger-fg ring-danger-solid/25" },
  uploading: { text: "Uploading", cls: ACCENT_PILL },
  transcribing: { text: "Transcribing", cls: ACCENT_PILL },
  kept: { text: "Not sent yet", cls: WARN_PILL },
  error: { text: "Microphone problem", cls: WARN_PILL },
};

const MIC_ERRORS: RecorderError[] = ["unsupported", "insecure", "denied", "no_device", "busy"];

/**
 * Voice answer input: one big tap-to-start / tap-to-stop button, a timer, a level meter, and the
 * upload state. Stopping sends the recording right away (`onRecorded`); if the upload fails the
 * parent keeps it (`failedRecording`) so the user can retry without re-recording.
 */
export function VoiceRecorder({
  onRecorded,
  onRecordStart,
  onRetry,
  onDiscardFailed,
  onSwitchToText,
  onAnnounce,
  sending,
  uploadProgress,
  failedRecording,
  blockedReason,
  buttonRef,
}: {
  onRecorded: (r: Recording) => void;
  /** Called when recording starts (the page stops the interviewer's voice). */
  onRecordStart: () => void;
  onRetry: () => void;
  onDiscardFailed: () => void;
  onSwitchToText: () => void;
  onAnnounce: (message: string) => void;
  sending: boolean;
  /** 0..1 while uploading; 1 = uploaded, now transcribing. null when idle. */
  uploadProgress: number | null;
  failedRecording: Recording | null;
  blockedReason: string | null;
  buttonRef: React.RefObject<HTMLButtonElement | null>;
}) {
  const rec = useRecorder();
  const { status, error, elapsed, maxSeconds, meterRef } = rec;
  const recording = status === "recording";
  const requesting = status === "requesting";

  // Hand the finished recording to the page exactly once.
  const handed = useRef<Recording | null>(null);
  const onRecordedRef = useRef(onRecorded);
  const onAnnounceRef = useRef(onAnnounce);
  useEffect(() => {
    onRecordedRef.current = onRecorded;
    onAnnounceRef.current = onAnnounce;
  });
  useEffect(() => {
    if (rec.recording && handed.current !== rec.recording) {
      handed.current = rec.recording;
      onRecordedRef.current(rec.recording);
    }
  }, [rec.recording]);
  useEffect(() => {
    if (error) onAnnounceRef.current(RECORDER_ERROR_TEXT[error]);
  }, [error]);
  // Lazy-loaded and remounted per question: when focus was lost (the previous control just
  // unmounted), put it on the record button so keyboard users can answer right away.
  useEffect(() => {
    const active = document.activeElement;
    if (!active || active === document.body) buttonRef.current?.focus({ preventScroll: true });
  }, [buttonRef]);

  const remaining = Math.max(0, maxSeconds - elapsed);
  const warn = recording && remaining <= 15;
  const announcedWarn = useRef(false);
  useEffect(() => {
    if (!recording) announcedWarn.current = false;
    else if (warn && !announcedWarn.current) {
      announcedWarn.current = true;
      onAnnounceRef.current("15 seconds left. Recording stops automatically at 2 minutes.");
    }
  }, [recording, warn]);

  const busy = sending || requesting;
  const disabled = sending || (!recording && (blockedReason !== null || failedRecording !== null));

  function toggle() {
    if (recording) {
      rec.stop();
      onAnnounce("Recording stopped. Uploading your answer…");
    } else if (!busy) {
      onRecordStart();
      rec.reset();
      void rec.start();
      onAnnounce("Recording. Tap the button again when you finish.");
    }
  }

  const micBlocked = error !== null && MIC_ERRORS.includes(error);
  const label = recording
    ? "Stop recording and send your answer"
    : requesting
      ? "Waiting for microphone permission"
      : "Start recording your answer";

  // One visible state at a time (shown as a pill next to the heading).
  type Phase =
    "idle" | "requesting" | "recording" | "uploading" | "transcribing" | "kept" | "error";
  const phase: Phase = sending
    ? uploadProgress === null || uploadProgress >= 1
      ? "transcribing"
      : "uploading"
    : recording
      ? "recording"
      : requesting
        ? "requesting"
        : failedRecording
          ? "kept"
          : error
            ? "error"
            : "idle";

  let statusText: string;
  if (sending)
    statusText =
      uploadProgress === null || uploadProgress >= 1
        ? "Transcribing your answer…"
        : uploadProgress > 0
          ? `Uploading… ${Math.round(uploadProgress * 100)}%`
          : "Sending your answer…";
  else if (recording) statusText = "Recording… tap to stop";
  else if (requesting) statusText = "Allow microphone access in your browser…";
  else if (failedRecording) statusText = "Your recording is saved on this page.";
  else statusText = "Tap the microphone and answer out loud";

  return (
    <section
      aria-labelledby="voice-answer-heading"
      className="border-border bg-surface shadow-card space-y-4 rounded-2xl border p-4 sm:p-6"
    >
      <div className="flex items-center justify-between gap-3">
        <h2 id="voice-answer-heading" className="font-medium">
          Your answer (voice)
        </h2>
        <span
          aria-hidden
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset",
            PILL[phase].cls,
          )}
        >
          {phase === "recording" && (
            <span className="bg-danger-solid size-2 animate-pulse rounded-full motion-reduce:animate-none" />
          )}
          {PILL[phase].text}
        </span>
      </div>

      <div className="flex flex-col items-center gap-3 text-center">
        <button
          ref={buttonRef}
          type="button"
          onClick={toggle}
          disabled={disabled}
          aria-label={label}
          aria-describedby="recorder-status recorder-hint"
          className={cn(
            "relative flex size-24 items-center justify-center rounded-full text-white shadow-lg transition-[background-color,transform] active:scale-95 disabled:cursor-not-allowed disabled:opacity-55 motion-reduce:transition-none sm:size-20",
            focusRing,
            recording
              ? "bg-danger-solid hover:bg-danger-fg"
              : "bg-accent hover:bg-accent-hover disabled:hover:bg-accent",
          )}
        >
          {recording ? (
            <span aria-hidden className="size-8 rounded-md bg-white" />
          ) : busy ? (
            <span
              aria-hidden
              className="size-8 animate-spin rounded-full border-4 border-white/40 border-t-white motion-reduce:animate-none"
            />
          ) : (
            <Mic className="size-10" strokeWidth={2} />
          )}
          {recording && (
            <span
              aria-hidden
              className="bg-danger-solid absolute inset-0 animate-ping rounded-full opacity-20 motion-reduce:hidden"
            />
          )}
        </button>

        <p id="recorder-status" className="text-fg text-sm font-medium" aria-live="off">
          {statusText}
        </p>

        <p
          className={cn(
            "font-mono text-3xl tabular-nums",
            warn ? "text-danger-fg" : recording ? "text-fg" : "text-fg-subtle",
          )}
          aria-label={`Recording time ${formatClock(elapsed)} of ${formatClock(maxSeconds)}`}
        >
          {formatClock(elapsed)}{" "}
          <span className="text-fg-subtle text-base">/ {formatClock(maxSeconds)}</span>
        </p>

        {/* Level meter: --level (0..1) is set by the recorder hook without re-rendering. */}
        <div
          aria-hidden
          className="bg-surface-sunken h-2 w-full max-w-xs overflow-hidden rounded-full"
        >
          <div
            ref={meterRef}
            data-testid="level-meter"
            className={cn(
              "h-full origin-left rounded-full transition-transform duration-75 motion-reduce:transition-none",
              recording ? "bg-success-solid" : "bg-border-strong",
            )}
            style={{ transform: "scaleX(var(--level, 0))" }}
          />
        </div>

        {sending && (
          <div
            role="progressbar"
            aria-label="Upload progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round((uploadProgress ?? 1) * 100)}
            className="bg-surface-sunken h-1.5 w-full max-w-xs overflow-hidden rounded-full"
          >
            <div
              className="bg-accent h-full origin-left rounded-full transition-transform motion-reduce:transition-none"
              style={{ transform: `scaleX(${uploadProgress ?? 1})` }}
            />
          </div>
        )}

        <p id="recorder-hint" className="text-fg-subtle max-w-md text-xs">
          Up to 2 minutes.
          <span className="pointer-coarse:sr-only">
            {" "}
            Press Space or Enter on the button to start and stop.
          </span>{" "}
          Audio is only used to transcribe your answer and is never stored.
          {blockedReason ? ` ${blockedReason}.` : ""}
        </p>
      </div>

      {error && (
        <div
          role="alert"
          className="border-warning-solid/30 bg-warning-soft text-warning-fg rounded-xl border p-4 text-sm"
        >
          <p>{RECORDER_ERROR_TEXT[error]}</p>
          {micBlocked && (
            <Button onClick={onSwitchToText} className="mt-3 w-full sm:w-auto">
              Type your answer instead
            </Button>
          )}
        </div>
      )}

      {failedRecording && !sending && (
        <div className="flex flex-col gap-2 sm:flex-row sm:justify-center">
          <Button onClick={onRetry} disabled={blockedReason !== null} className="w-full sm:w-auto">
            Retry upload
          </Button>
          <Button
            variant="secondary"
            onClick={() => {
              onDiscardFailed();
              rec.reset();
              requestAnimationFrame(() => buttonRef.current?.focus());
            }}
            className="w-full sm:w-auto"
          >
            Record again
          </Button>
          <Button variant="secondary" onClick={onSwitchToText} className="w-full sm:w-auto">
            Type instead
          </Button>
        </div>
      )}
    </section>
  );
}
