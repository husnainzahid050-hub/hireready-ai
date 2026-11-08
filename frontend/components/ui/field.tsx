import type { ComponentProps } from "react";

import { cn, focusRing } from "@/components/ui/cn";

/** Shared look for text inputs and textareas. `aria-invalid` switches to the danger border. */
export const controlClasses = cn(
  "block w-full rounded-xl border border-border-strong bg-surface px-3.5 text-sm text-fg shadow-sm placeholder:text-fg-subtle",
  "transition-[border-color,box-shadow] duration-150 hover:border-fg-subtle",
  "focus-visible:border-ring focus-visible:ring-4 focus-visible:ring-ring/20 focus-visible:outline-none",
  "aria-invalid:border-danger-solid aria-invalid:focus-visible:ring-danger-solid/20",
  "disabled:cursor-not-allowed disabled:opacity-60",
);

export function Label({ className, ...props }: ComponentProps<"label">) {
  return <label className={cn("text-fg block text-sm font-medium", className)} {...props} />;
}

/** Secondary text next to a label, e.g. "(optional)". */
export function Hint({ className, ...props }: ComponentProps<"span">) {
  return <span className={cn("text-fg-subtle font-normal", className)} {...props} />;
}

export function Input({ className, ...props }: ComponentProps<"input">) {
  return <input className={cn(controlClasses, "min-h-11 py-2", className)} {...props} />;
}

export function Textarea({ className, ...props }: ComponentProps<"textarea">) {
  return <textarea className={cn(controlClasses, "py-3 leading-relaxed", className)} {...props} />;
}

/** Native checkbox, accent-coloured, 20px, with the shared focus ring. */
export function Checkbox({ className, ...props }: Omit<ComponentProps<"input">, "type">) {
  return (
    <input
      type="checkbox"
      className={cn(
        "accent-accent size-5 shrink-0 cursor-pointer rounded disabled:cursor-not-allowed disabled:opacity-50",
        focusRing,
        className,
      )}
      {...props}
    />
  );
}

export function FieldError({ className, ...props }: ComponentProps<"p">) {
  return <p role="alert" className={cn("text-danger-fg text-sm", className)} {...props} />;
}
