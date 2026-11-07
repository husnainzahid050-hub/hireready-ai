/** Join class names, skipping falsy values. Tiny stand-in for `clsx` (no dependency). */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

/**
 * The one focus style used everywhere: a 2px outline in the accent colour, offset from the
 * element so it stays visible on coloured buttons. Only shown for keyboard focus.
 */
export const focusRing =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring";
