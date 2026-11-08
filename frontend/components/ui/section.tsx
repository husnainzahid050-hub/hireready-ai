import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/components/ui/cn";

/** Page-width wrapper: one max width and gutter for every page. */
export function Container({
  className,
  size = "default",
  ...props
}: ComponentProps<"div"> & { size?: "default" | "narrow" | "prose" }) {
  return (
    <div
      className={cn(
        "mx-auto w-full px-5 sm:px-6",
        size === "default" && "max-w-6xl",
        size === "narrow" && "max-w-3xl",
        size === "prose" && "max-w-2xl",
        className,
      )}
      {...props}
    />
  );
}

/** Eyebrow + heading + intro, used at the top of every landing/engineering section. */
export function SectionHeading({
  id,
  eyebrow,
  title,
  children,
  align = "left",
}: {
  id?: string;
  eyebrow?: string;
  title: ReactNode;
  children?: ReactNode;
  align?: "left" | "center";
}) {
  return (
    <div className={cn("max-w-2xl space-y-3", align === "center" && "mx-auto text-center")}>
      {eyebrow && (
        <p className="text-link text-sm font-semibold tracking-wide uppercase">{eyebrow}</p>
      )}
      <h2 id={id} className="text-2xl font-semibold tracking-tight text-balance sm:text-3xl">
        {title}
      </h2>
      {children && <p className="text-fg-muted text-base text-pretty sm:text-lg">{children}</p>}
    </div>
  );
}
