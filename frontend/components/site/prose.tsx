import type { ComponentProps } from "react";

import { cn, focusRing } from "@/components/ui/cn";

/** Text link with the shared style (underlined, accent colour, focus ring). */
export function TextLink({ className, ...props }: ComponentProps<"a">) {
  return (
    <a
      className={cn(
        "text-link rounded font-medium underline underline-offset-2 hover:no-underline",
        focusRing,
        className,
      )}
      {...props}
    />
  );
}

/** A titled section of a long-form page (engineering, privacy). */
export function DocSection({
  id,
  title,
  children,
  className,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section aria-labelledby={id} className={cn("space-y-5", className)}>
      <h2 id={id} className="text-2xl font-semibold tracking-tight">
        <a href={`#${id}`} className={cn("rounded hover:underline", focusRing)}>
          {title}
        </a>
      </h2>
      {children}
    </section>
  );
}

/** Simple responsive table wrapper (horizontal scroll on phones instead of overflow). */
export function DataTable({
  caption,
  head,
  rows,
}: {
  caption: string;
  head: string[];
  rows: React.ReactNode[][];
}) {
  return (
    <div
      className={cn("border-border bg-surface overflow-x-auto rounded-2xl border", focusRing)}
      tabIndex={0}
      role="region"
      aria-label={caption}
    >
      <table className="w-full min-w-[34rem] text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-surface-muted text-fg-muted">
          <tr>
            {head.map((h) => (
              <th key={h} scope="col" className="px-4 py-3 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-border divide-y">
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((c, j) =>
                j === 0 ? (
                  <th key={j} scope="row" className="px-4 py-3 align-top font-medium">
                    {c}
                  </th>
                ) : (
                  <td key={j} className="text-fg-muted px-4 py-3 align-top">
                    {c}
                  </td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
