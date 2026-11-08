"use client";

import { FOCUS_RING } from "@/components/interview/parts";

const BTN = `inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-zinc-300 bg-white px-3 text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-950 dark:hover:bg-zinc-800 ${FOCUS_RING}`;

/** Interviewer voice controls: mute (persisted) and replay the current question. */
export function VoiceControls({
  muted,
  onToggleMute,
  onReplay,
  speaking,
}: {
  muted: boolean;
  onToggleMute: () => void;
  onReplay: () => void;
  speaking: boolean;
}) {
  return (
    <div className="flex items-center gap-2">
      <button type="button" onClick={onReplay} className={BTN} disabled={speaking}>
        <svg aria-hidden viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
          <path d="M10 3a7 7 0 1 0 6.93 8h-2.03A5 5 0 1 1 10 5c1.38 0 2.63.56 3.54 1.46L11 9h6V3l-2.05 2.05A6.98 6.98 0 0 0 10 3Z" />
        </svg>
        Replay
        <span className="sr-only"> the question out loud</span>
      </button>
      <button
        type="button"
        onClick={onToggleMute}
        aria-pressed={muted}
        className={`${BTN} aria-pressed:border-indigo-600 aria-pressed:bg-indigo-50 dark:aria-pressed:bg-indigo-950`}
        title={muted ? "Questions are not read aloud" : "Questions are read aloud"}
      >
        <svg aria-hidden viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
          {muted ? (
            <path d="M9 4 5 8H2v4h3l4 4V4Zm4.3 2.3-1.4 1.4L14.2 10l-2.3 2.3 1.4 1.4 2.3-2.3 2.3 2.3 1.4-1.4L17 10l2.3-2.3-1.4-1.4L15.6 8.6l-2.3-2.3Z" />
          ) : (
            <path d="M9 4 5 8H2v4h3l4 4V4Zm3.5 2.1a5 5 0 0 1 0 7.8l-1.2-1.6a3 3 0 0 0 0-4.6l1.2-1.6Zm2.4-2.4a8.5 8.5 0 0 1 0 12.6l-1.2-1.6a6.5 6.5 0 0 0 0-9.4l1.2-1.6Z" />
          )}
        </svg>
        Mute voice
      </button>
    </div>
  );
}
