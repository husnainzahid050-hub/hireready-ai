import { cn } from "@/components/ui/cn";

/** Ring gauge for a 0-100 score. `label` names the score for screen readers ("Match score"). */
export function ScoreGauge({
  value,
  size = "lg",
  label,
  bandLabel,
  stroke,
}: {
  value: number;
  size?: "sm" | "lg";
  label: string;
  bandLabel: string;
  /** Tailwind stroke class for the band colour, e.g. "stroke-success-solid". */
  stroke: string;
}) {
  const r = 52;
  const c = 2 * Math.PI * r;
  return (
    <div className={cn("relative shrink-0", size === "lg" ? "size-36" : "size-16")}>
      <svg viewBox="0 0 120 120" className="size-full -rotate-90" aria-hidden>
        <circle
          cx="60"
          cy="60"
          r={r}
          fill="none"
          strokeWidth="10"
          className="stroke-surface-sunken"
        />
        <circle
          cx="60"
          cy="60"
          r={r}
          fill="none"
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - value / 100)}
          className={cn(
            stroke,
            "transition-[stroke-dashoffset] duration-700 motion-reduce:transition-none",
          )}
        />
      </svg>
      <span
        role="img"
        aria-label={`${label} ${value} out of 100: ${bandLabel}`}
        className="absolute inset-0 flex flex-col items-center justify-center"
      >
        <span
          aria-hidden
          className={cn("font-semibold tabular-nums", size === "lg" ? "text-4xl" : "text-lg")}
        >
          {value}
        </span>
        {size === "lg" && (
          <span aria-hidden className="text-fg-subtle text-xs">
            / 100
          </span>
        )}
      </span>
    </div>
  );
}
