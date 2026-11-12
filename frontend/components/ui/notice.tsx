import type { ReactNode } from "react";

import { cn } from "@/components/ui/cn";
import { Alert, Check } from "@/components/ui/icons";

export type NoticeTone = "error" | "warning" | "info" | "success";

const TONE: Record<NoticeTone, string> = {
  error: "border-danger-solid/25 bg-danger-soft text-danger-fg",
  warning: "border-warning-solid/30 bg-warning-soft text-warning-fg",
  info: "border-accent/20 bg-accent-soft text-accent-soft-fg",
  success: "border-success-solid/25 bg-success-soft text-success-fg",
};

/**
 * Inline message panel. Errors are announced immediately (`role="alert"`), everything else
 * politely (`role="status"`). Children may contain buttons and links.
 */
export function Notice({
  tone,
  title,
  children,
  className,
}: {
  tone: NoticeTone;
  title?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  const Icon = tone === "success" ? Check : Alert;
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={cn("flex gap-3 rounded-xl border p-4 text-sm", TONE[tone], className)}
    >
      <Icon className="mt-0.5 size-5 shrink-0" />
      <div className="min-w-0 flex-1 space-y-1">
        {title && <p className="font-medium">{title}</p>}
        {children}
      </div>
    </div>
  );
}

/** Small spinning ring for buttons; hidden from screen readers (the button text says it). */
export function Spinner({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-block size-4 animate-spin rounded-full border-2 border-current border-t-transparent opacity-80 motion-reduce:animate-none",
        className,
      )}
    />
  );
}
