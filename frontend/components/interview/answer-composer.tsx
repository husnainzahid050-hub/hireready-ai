"use client";

import { BUTTON_PRIMARY, FOCUS_RING } from "@/components/interview/parts";
import { ANSWER_MAX } from "@/lib/api";

/**
 * Text answer input. Phase 4 adds a voice recorder as a sibling input method that produces
 * the same `onSubmit(text)` call (from the transcript), so the parent logic stays the same.
 */
export function AnswerComposer({
  value,
  onChange,
  onSubmit,
  sending,
  blockedReason,
  textareaRef,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  sending: boolean;
  /** When set, sending is temporarily blocked (e.g. rate limited); shown next to the button. */
  blockedReason: string | null;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
}) {
  const length = value.length;
  const empty = value.trim().length === 0;
  const near = length > ANSWER_MAX * 0.9;
  const canSend = !sending && !empty && !blockedReason && length <= ANSWER_MAX;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (canSend) onSubmit();
      }}
      className="space-y-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label htmlFor="answer" className="font-medium">
          Your answer
        </label>
        <span
          className="inline-flex items-center gap-1.5 rounded-full border border-dashed border-zinc-300 px-3 py-1 text-xs text-zinc-600 dark:border-zinc-700 dark:text-zinc-400"
          title="Voice answers arrive in the next update"
        >
          <svg aria-hidden viewBox="0 0 20 20" className="h-3.5 w-3.5" fill="currentColor">
            <path d="M10 13a3 3 0 0 0 3-3V5a3 3 0 1 0-6 0v5a3 3 0 0 0 3 3Zm5-3a1 1 0 1 1 2 0 7 7 0 0 1-6 6.93V19a1 1 0 1 1-2 0v-2.07A7 7 0 0 1 3 10a1 1 0 1 1 2 0 5 5 0 0 0 10 0Z" />
          </svg>
          Voice mode coming soon
        </span>
      </div>
      <textarea
        id="answer"
        ref={textareaRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            if (canSend) onSubmit();
          }
        }}
        // readOnly (not disabled) while sending, so keyboard focus stays in place.
        readOnly={sending}
        maxLength={ANSWER_MAX}
        rows={7}
        aria-describedby="answer-hint answer-count"
        placeholder="Type your answer as you would say it in the interview…"
        className={`block w-full resize-y rounded-xl border border-zinc-300 bg-white p-3 text-base leading-relaxed placeholder:text-zinc-500 dark:border-zinc-700 dark:bg-zinc-950 dark:placeholder:text-zinc-500 ${FOCUS_RING} ${
          sending ? "opacity-70" : ""
        }`}
      />
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="flex flex-wrap gap-x-3 text-xs text-zinc-600 dark:text-zinc-400">
          <span id="answer-hint">
            Press{" "}
            <kbd className="rounded border border-zinc-300 px-1 font-sans dark:border-zinc-700">
              Ctrl
            </kbd>{" "}
            /{" "}
            <kbd className="rounded border border-zinc-300 px-1 font-sans dark:border-zinc-700">
              ⌘
            </kbd>{" "}
            +{" "}
            <kbd className="rounded border border-zinc-300 px-1 font-sans dark:border-zinc-700">
              Enter
            </kbd>{" "}
            to send.
          </span>
          <span
            id="answer-count"
            className={`tabular-nums ${near ? "font-medium text-amber-800 dark:text-amber-300" : ""}`}
          >
            {length.toLocaleString("en-US")} / {ANSWER_MAX.toLocaleString("en-US")} characters
          </span>
        </p>
        <div className="flex items-center gap-3">
          {blockedReason && (
            <span className="text-xs text-zinc-600 dark:text-zinc-400">{blockedReason}</span>
          )}
          <button
            type="submit"
            disabled={!canSend}
            className={`${BUTTON_PRIMARY} w-full sm:w-auto`}
          >
            {sending ? (
              <>
                <span
                  aria-hidden
                  className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white motion-reduce:animate-none"
                />
                Sending…
              </>
            ) : (
              "Send answer"
            )}
          </button>
        </div>
      </div>
    </form>
  );
}
