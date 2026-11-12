"use client";

import { useState } from "react";

import { questionLabel } from "@/components/interview/parts";
import { cn, focusRing } from "@/components/ui/cn";
import { ChevronDown } from "@/components/ui/icons";
import type { InterviewTurn, Question } from "@/lib/types";

type Entry = { question: Question; answer_text: string; pending?: boolean };

/**
 * Previous questions and answers. Collapsible on small screens (a disclosure button),
 * always expanded from `lg` up where it sits in a sidebar.
 */
export function Transcript({
  history,
  pending,
  defaultOpen = false,
}: {
  history: InterviewTurn["history"];
  pending: Entry | null;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const entries: Entry[] = pending ? [...history, { ...pending, pending: true }] : history;
  const count = entries.length;

  return (
    <section aria-labelledby="transcript-heading" className="space-y-3">
      <h2 id="transcript-heading" className="text-base font-semibold">
        <button
          type="button"
          aria-expanded={open}
          aria-controls="transcript-list"
          onClick={() => setOpen((o) => !o)}
          className={cn(
            "border-border bg-surface hover:bg-surface-muted flex min-h-11 w-full items-center justify-between gap-2 rounded-lg border px-4 text-left lg:hidden",
            focusRing,
          )}
        >
          <span>
            Transcript <span className="text-fg-muted font-normal">({count})</span>
          </span>
          <ChevronDown
            className={cn(
              "text-fg-subtle size-4 transition-transform motion-reduce:transition-none",
              open && "rotate-180",
            )}
          />
        </button>
        <span className="hidden lg:inline">
          Transcript <span className="text-fg-muted font-normal">({count})</span>
        </span>
      </h2>

      <div id="transcript-list" className={open ? "block" : "hidden lg:block"}>
        {count === 0 ? (
          <p className="text-fg-muted text-sm">Your questions and answers will appear here.</p>
        ) : (
          <ol className="space-y-3">
            {entries.map((e, i) => (
              <li
                key={`${e.question.id}-${i}`}
                className="border-border bg-surface space-y-2 rounded-xl border p-3 text-sm"
              >
                <p className="text-fg-subtle text-xs font-medium">
                  Q{e.question.order} · {questionLabel(e.question)}
                </p>
                <p className="font-medium">{e.question.text}</p>
                <p
                  className={cn(
                    "border-accent/40 text-fg-muted border-l-2 pl-3 whitespace-pre-wrap",
                    e.pending && "opacity-70",
                  )}
                >
                  <span className="sr-only">Your answer: </span>
                  {e.answer_text}
                </p>
                {e.pending && <p className="text-fg-subtle text-xs">Sending…</p>}
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}
