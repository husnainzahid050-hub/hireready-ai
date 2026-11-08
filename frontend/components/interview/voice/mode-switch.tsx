"use client";

import type { AnswerMode } from "@/lib/prefs";

/**
 * Voice / Text answer mode as a radio group (arrow keys move between options natively).
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
  const options: { value: AnswerMode; label: string }[] = [
    { value: "voice", label: "Voice" },
    { value: "text", label: "Text" },
  ];
  return (
    <fieldset className="space-y-1">
      <legend className="sr-only">Answer mode</legend>
      <div className="inline-flex rounded-full bg-zinc-100 p-1 dark:bg-zinc-800">
        {options.map((o) => {
          const off = disabled || (o.value === "voice" && voiceUnavailable !== null);
          return (
            <label
              key={o.value}
              className={`relative inline-flex min-h-11 min-w-20 items-center justify-center rounded-full px-4 text-sm font-medium has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-indigo-600 ${
                mode === o.value
                  ? "bg-white text-zinc-900 shadow dark:bg-zinc-950 dark:text-zinc-100"
                  : "text-zinc-700 dark:text-zinc-300"
              } ${off ? "cursor-not-allowed opacity-50" : "cursor-pointer"}`}
            >
              <input
                type="radio"
                name="answer-mode"
                value={o.value}
                checked={mode === o.value}
                disabled={off}
                onChange={() => onChange(o.value)}
                aria-describedby={
                  o.value === "voice" && voiceUnavailable ? "voice-off-reason" : undefined
                }
                className="sr-only"
              />
              {o.label}
            </label>
          );
        })}
      </div>
      {voiceUnavailable && (
        <p id="voice-off-reason" className="text-xs text-zinc-600 dark:text-zinc-400">
          {voiceUnavailable}
        </p>
      )}
    </fieldset>
  );
}
