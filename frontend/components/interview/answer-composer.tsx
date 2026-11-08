"use client";

import { BUTTON_PRIMARY, FOCUS_RING } from "@/components/interview/parts";
import { ANSWER_MAX } from "@/lib/api";

/**
 * Text answer input. The voice recorder (components/interview/voice) is the sibling input; the
 * page switches between them with the Voice / Text mode switch.
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
