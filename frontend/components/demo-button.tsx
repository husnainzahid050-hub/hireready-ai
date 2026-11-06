"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError, createSession } from "@/lib/api";

export function DemoButton({ className = "" }: { className?: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const { session_id } = await createSession(
        {
          mode: "text",
          difficulty: "junior",
          interview_type: "mixed",
          email: null,
          email_opt_in: false,
          consent: true,
        },
        true,
      );
      router.push(`/session/${session_id}/analysis`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not start the demo. Please try again.");
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        onClick={start}
        disabled={busy}
        className={`rounded-lg border border-zinc-300 px-5 py-3 font-medium transition-colors hover:bg-zinc-100 focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:outline-none disabled:opacity-60 dark:border-zinc-700 dark:hover:bg-zinc-900 ${className}`}
      >
        {busy ? "Starting demo…" : "Try with a sample CV"}
      </button>
      {error && (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      )}
    </div>
  );
}
