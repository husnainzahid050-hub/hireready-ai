"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { buttonClasses, type ButtonSize, type ButtonVariant } from "@/components/ui/button";
import { cn } from "@/components/ui/cn";
import { ApiError, createSession } from "@/lib/api";

export function DemoButton({
  className = "",
  variant = "secondary",
  size = "lg",
}: {
  className?: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
}) {
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
        aria-busy={busy}
        className={buttonClasses({ variant, size, className })}
      >
        {busy && (
          <span
            aria-hidden
            className="size-4 animate-spin rounded-full border-2 border-current border-r-transparent"
          />
        )}
        {busy ? "Starting demo…" : "Try with a sample CV"}
      </button>
      {error && (
        <p role="alert" className={cn("max-w-xs text-sm text-danger-fg")}>
          {error}
        </p>
      )}
    </div>
  );
}
