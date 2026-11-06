"use client";

import { useState } from "react";

import { FOCUS_RING, questionLabel } from "@/components/interview/parts";
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
          className={`flex min-h-11 w-full items-center justify-between gap-2 rounded-lg border border-zinc-200 px-4 text-left lg:hidden dark:border-zinc-800 ${FOCUS_RING}`}
        >
          <span>
            Transcript{" "}
            <span className="font-normal text-zinc-600 dark:text-zinc-400">({count})</span>
          </span>
          <span
            aria-hidden
            className={`transition-transform motion-reduce:transition-none ${open ? "rotate-180" : ""}`}
          >
            ▾
          </span>
        </button>
        <span className="hidden lg:inline">
          Transcript <span className="font-normal text-zinc-600 dark:text-zinc-400">({count})</span>
        </span>
      </h2>

      <div id="transcript-list" className={open ? "block" : "hidden lg:block"}>
        {count === 0 ? (
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            Your questions and answers will appear here.
          </p>
        ) : (
          <ol className="space-y-4">
            {entries.map((e, i) => (
              <li
                key={`${e.question.id}-${i}`}
                className="space-y-2 rounded-xl border border-zinc-200 p-3 text-sm dark:border-zinc-800"
              >
                <p className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
                  Q{e.question.order} · {questionLabel(e.question)}
                </p>
                <p className="font-medium">{e.question.text}</p>
                <p
                  className={`border-l-2 border-indigo-300 pl-3 whitespace-pre-wrap text-zinc-700 dark:border-indigo-800 dark:text-zinc-300 ${
                    e.pending ? "opacity-70" : ""
                  }`}
                >
                  <span className="sr-only">Your answer: </span>
                  {e.answer_text}
                </p>
                {e.pending && <p className="text-xs text-zinc-600 dark:text-zinc-400">Sending…</p>}
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}
