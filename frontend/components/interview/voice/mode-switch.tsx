"use client";

import { cn } from "@/components/ui/cn";
import { Keyboard, Mic } from "@/components/ui/icons";
import type { AnswerMode } from "@/lib/prefs";

/**
 * Voice / Text answer mode as a segmented radio group (arrow keys move between options natively).
 * Voice is disabled with a reason when the browser can't record.
 */
export function ModeSwitch({
  mode,
  onChange,
  voiceUnavailable,
  disabled,
}: {
  mode: AnswerMode;
  onChange: (m: AnswerMode) => void;
  /** Why voice can't be used here (no mic support / insecure page), or null. */
  voiceUnavailable: string | null;
  disabled: boolean;
}) {
  const options: { value: AnswerMode; label: string; Icon: typeof Mic }[] = [
    { value: "voice", label: "Voice", Icon: Mic },
    { value: "text", label: "Text", Icon: Keyboard },
  ];
  return (
    <fieldset className="space-y-1.5">
      <legend className="text-fg-muted mb-1.5 text-sm font-medium">Answer by</legend>
      <div className="border-border bg-surface-sunken grid w-full grid-cols-2 rounded-xl border p-1 sm:inline-grid sm:w-auto">
        {options.map(({ value, label, Icon }) => {
          const off = disabled || (value === "voice" && voiceUnavailable !== null);
          const active = mode === value;
          return (
            <label
              key={value}
              className={cn(
                "relative inline-flex min-h-11 min-w-28 items-center justify-center gap-2 rounded-lg px-4 text-sm font-medium transition-colors motion-reduce:transition-none",
                "has-[:focus-visible]:outline-ring has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2",
                active
                  ? "bg-surface text-fg shadow-card ring-border ring-1"
                  : "text-fg-muted hover:text-fg",
                off ? "cursor-not-allowed opacity-55" : "cursor-pointer",
              )}
            >
              <input
                type="radio"
                name="answer-mode"
                value={value}
                checked={active}
                disabled={off}
                onChange={() => onChange(value)}
                aria-describedby={
                  value === "voice" && voiceUnavailable ? "voice-off-reason" : undefined
                }
                className="sr-only"
              />
              <Icon className="size-4" />
              {label}
            </label>
          );
        })}
      </div>
      {voiceUnavailable && (
        <p id="voice-off-reason" className="text-fg-subtle text-xs">
          {voiceUnavailable}
        </p>
      )}
    </fieldset>
  );
}
