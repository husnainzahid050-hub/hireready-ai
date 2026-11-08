"use client";

import { useEffect, useRef } from "react";

import { BUTTON_PRIMARY, BUTTON_SECONDARY, FOCUS_RING } from "@/components/interview/parts";
import {
  formatClock,
  type Recording,
  RECORDER_ERROR_TEXT,
  type RecorderError,
  useRecorder,
} from "@/lib/use-recorder";

const MIC_ERRORS: RecorderError[] = ["unsupported", "insecure", "denied", "no_device", "busy"];

function MicIcon({ className }: { className?: string }) {
  return (
    <svg aria-hidden viewBox="0 0 20 20" className={className} fill="currentColor">
      <path d="M10 13a3 3 0 0 0 3-3V5a3 3 0 1 0-6 0v5a3 3 0 0 0 3 3Zm5-3a1 1 0 1 1 2 0 7 7 0 0 1-6 6.93V19a1 1 0 1 1-2 0v-2.07A7 7 0 0 1 3 10a1 1 0 1 1 2 0 5 5 0 0 0 10 0Z" />
    </svg>
  );
}

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
      className="space-y-4 rounded-2xl border border-zinc-200 p-4 sm:p-6 dark:border-zinc-800"
    >
      <h2 id="voice-answer-heading" className="font-medium">
        Your answer (voice)
      </h2>

      <div className="flex flex-col items-center gap-3 text-center">
        <button
          ref={buttonRef}
          type="button"
          onClick={toggle}
          disabled={disabled}
          aria-label={label}
          aria-describedby="recorder-status recorder-hint"
          className={`relative flex h-20 w-20 items-center justify-center rounded-full text-white shadow-md transition-colors disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none ${FOCUS_RING} ${
            recording
              ? "bg-red-600 hover:bg-red-700"
              : "bg-indigo-600 hover:bg-indigo-700 disabled:hover:bg-indigo-600"
          }`}
        >
          {recording ? (
            <span aria-hidden className="h-7 w-7 rounded-md bg-white" />
          ) : busy ? (
            <span
              aria-hidden
              className="h-7 w-7 animate-spin rounded-full border-4 border-white/40 border-t-white motion-reduce:animate-none"
            />
          ) : (
            <MicIcon className="h-9 w-9" />
          )}
          {recording && (
            <span
              aria-hidden
              className="absolute inset-0 animate-ping rounded-full bg-red-500 opacity-20 motion-reduce:hidden"
            />
          )}
        </button>

        <p id="recorder-status" className="text-sm font-medium" aria-live="off">
          {statusText}
        </p>

        <p
          className={`font-mono text-2xl tabular-nums ${warn ? "text-red-700 dark:text-red-400" : ""}`}
          aria-label={`Recording time ${formatClock(elapsed)} of ${formatClock(maxSeconds)}`}
        >
          {formatClock(elapsed)}{" "}
          <span className="text-base text-zinc-500 dark:text-zinc-400">
            / {formatClock(maxSeconds)}
          </span>
        </p>

        {/* Level meter: --level (0..1) is set by the recorder hook without re-rendering. */}
        <div
          aria-hidden
          className="h-2 w-full max-w-xs overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800"
        >
          <div
            ref={meterRef}
            data-testid="level-meter"
            className={`h-full origin-left rounded-full transition-transform duration-75 motion-reduce:transition-none ${
              recording ? "bg-emerald-500" : "bg-zinc-400"
            }`}
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
            className="h-1.5 w-full max-w-xs overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800"
          >
            <div
              className="h-full origin-left rounded-full bg-indigo-600 transition-transform motion-reduce:transition-none"
              style={{ transform: `scaleX(${uploadProgress ?? 1})` }}
            />
          </div>
        )}

        <p id="recorder-hint" className="text-xs text-zinc-600 dark:text-zinc-400">
          Up to 2 minutes. Press Space or Enter on the button to start and stop. Audio is only used
          to transcribe your answer and is never stored.
          {blockedReason ? ` ${blockedReason}.` : ""}
        </p>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded-xl bg-amber-50 p-4 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200"
        >
          <p>{RECORDER_ERROR_TEXT[error]}</p>
          {micBlocked && (
            <button
              type="button"
              onClick={onSwitchToText}
              className={`${BUTTON_PRIMARY} mt-3 w-full sm:w-auto`}
            >
              Type your answer instead
            </button>
          )}
        </div>
      )}

      {failedRecording && !sending && (
        <div className="flex flex-col gap-2 sm:flex-row sm:justify-center">
          <button
            type="button"
            onClick={onRetry}
            disabled={blockedReason !== null}
            className={`${BUTTON_PRIMARY} w-full sm:w-auto`}
          >
            Retry upload
          </button>
          <button
            type="button"
            onClick={() => {
              onDiscardFailed();
              rec.reset();
              requestAnimationFrame(() => buttonRef.current?.focus());
            }}
            className={`${BUTTON_SECONDARY} w-full sm:w-auto`}
          >
            Record again
          </button>
          <button
            type="button"
            onClick={onSwitchToText}
            className={`${BUTTON_SECONDARY} w-full sm:w-auto`}
          >
            Type instead
          </button>
        </div>
      )}
    </section>
  );
}
