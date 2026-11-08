import type { ComponentProps, ElementType } from "react";

import { cn } from "@/components/ui/cn";

type CardProps<T extends ElementType> = {
  as?: T;
  /** "raised" adds a soft shadow for hero/preview cards; "muted" is a tinted panel. */
  tone?: "default" | "raised" | "muted";
  padded?: boolean;
} & Omit<ComponentProps<T>, "as">;

export function Card<T extends ElementType = "div">({
  as,
  tone = "default",
  padded = true,
  className,
  ...props
}: CardProps<T>) {
  const Tag = (as ?? "div") as ElementType;
  return (
    <Tag
      className={cn(
        "border-border rounded-2xl border",
        tone === "default" && "bg-surface shadow-card",
        tone === "raised" && "bg-surface shadow-raised",
        tone === "muted" && "bg-surface-muted",
        padded && "p-5 sm:p-6",
        className,
      )}
      {...props}
    />
  );
}
