"use client";

import { buttonClasses } from "@/components/ui/button";
import { cn } from "@/components/ui/cn";
import { Textarea } from "@/components/ui/field";
import { ArrowRight } from "@/components/ui/icons";
import { Spinner } from "@/components/ui/notice";
import { ANSWER_MAX } from "@/lib/api";

const Kbd = ({ children }: { children: React.ReactNode }) => (
  <kbd className="border-border-strong bg-surface rounded border px-1 font-sans">{children}</kbd>
);

/**
 * Text answer input. The voice recorder (components/interview/voice) is the sibling input; the
 * page switches between them with the Voice / Text mode switch.
 *
 * The send button is never silently disabled: when it can't send it uses `aria-disabled` (still
 * focusable, readable contrast) and the line next to it says why.
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
  const why = sending
    ? null
    : blockedReason
      ? blockedReason
      : empty
        ? "Type your answer to send it"
        : null;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (canSend) onSubmit();
        else if (!sending) textareaRef.current?.focus();
      }}
      className="space-y-3"
    >
      <label htmlFor="answer" className="block font-medium">
        Your answer
      </label>
      <Textarea
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
        className={cn("resize-y text-base!", sending && "opacity-70")}
      />
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-fg-subtle flex flex-wrap gap-x-3 text-xs">
          <span id="answer-hint" className="pointer-coarse:sr-only">
            Press <Kbd>Ctrl</Kbd> / <Kbd>⌘</Kbd> + <Kbd>Enter</Kbd> to send.
          </span>
          <span
            id="answer-count"
            className={cn("tabular-nums", near && "text-warning-fg font-medium")}
          >
            {length.toLocaleString("en-US")} / {ANSWER_MAX.toLocaleString("en-US")} characters
          </span>
        </p>
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:gap-3">
          {why && (
            <span id="send-why" className="text-fg-subtle text-center text-xs sm:text-right">
              {why}
            </span>
          )}
          <button
            type="submit"
            aria-disabled={!canSend}
            aria-describedby={why ? "send-why" : undefined}
            className={buttonClasses({
              size: "lg",
              className: cn(
                "w-full sm:w-auto",
                !canSend &&
                  !sending &&
                  "bg-surface-sunken text-fg-muted hover:bg-surface-sunken cursor-not-allowed shadow-none active:translate-y-0",
                sending && "cursor-progress",
              ),
            })}
          >
            {sending ? (
              <>
                <Spinner />
                Sending…
              </>
            ) : (
              <>
                Send answer
                <ArrowRight className="size-4" />
              </>
            )}
          </button>
        </div>
      </div>
    </form>
  );
}
