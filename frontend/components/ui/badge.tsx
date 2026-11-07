import type { ComponentProps } from "react";

import { cn } from "@/components/ui/cn";

export type BadgeTone = "neutral" | "accent" | "success" | "warning" | "danger";

const TONE: Record<BadgeTone, string> = {
  neutral: "bg-surface-sunken text-fg-muted ring-border",
  accent: "bg-accent-soft text-accent-soft-fg ring-accent/20",
  success: "bg-success-soft text-success-fg ring-success-solid/20",
  warning: "bg-warning-soft text-warning-fg ring-warning-solid/25",
  danger: "bg-danger-soft text-danger-fg ring-danger-solid/20",
};

export function Badge({
  tone = "neutral",
  className,
  ...props
}: ComponentProps<"span"> & { tone?: BadgeTone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap ring-1 ring-inset",
        TONE[tone],
        className,
      )}
      {...props}
    />
  );
}
