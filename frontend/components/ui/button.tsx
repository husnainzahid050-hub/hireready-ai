import Link from "next/link";
import type { ComponentProps } from "react";

import { cn, focusRing } from "@/components/ui/cn";

export type ButtonVariant = "primary" | "secondary" | "ghost";
export type ButtonSize = "sm" | "md" | "lg";

const VARIANT: Record<ButtonVariant, string> = {
  primary:
    "bg-accent text-accent-fg shadow-sm hover:bg-accent-hover disabled:hover:bg-accent active:translate-y-px",
  secondary:
    "border border-border-strong bg-surface text-fg shadow-sm hover:bg-surface-sunken active:translate-y-px",
  ghost: "text-fg-muted hover:bg-surface-sunken hover:text-fg",
};

// Every size keeps a 44px touch target from md up (WCAG 2.5.5); sm is for dense toolbars.
const SIZE: Record<ButtonSize, string> = {
  sm: "min-h-9 px-3 text-sm rounded-lg",
  md: "min-h-11 px-4 text-sm rounded-lg",
  lg: "min-h-12 px-6 text-base rounded-xl",
};

/** Class string for anything that should look like a button (also usable on <a>). */
export function buttonClasses({
  variant = "primary",
  size = "md",
  className,
}: { variant?: ButtonVariant; size?: ButtonSize; className?: string } = {}) {
  return cn(
    "inline-flex items-center justify-center gap-2 font-medium whitespace-nowrap transition-[background-color,color,transform] duration-150 select-none disabled:cursor-not-allowed disabled:opacity-55",
    focusRing,
    VARIANT[variant],
    SIZE[size],
    className,
  );
}

type ButtonProps = ComponentProps<"button"> & { variant?: ButtonVariant; size?: ButtonSize };

export function Button({ variant, size, className, type = "button", ...props }: ButtonProps) {
  return <button type={type} className={buttonClasses({ variant, size, className })} {...props} />;
}

type ButtonLinkProps = ComponentProps<typeof Link> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
};

/** A Next.js <Link> styled as a button (navigation stays a link for screen readers). */
export function ButtonLink({ variant, size, className, ...props }: ButtonLinkProps) {
  return <Link className={buttonClasses({ variant, size, className })} {...props} />;
}
