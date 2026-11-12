# UX review: analysis and interview pages

Date: 2026-11-08. Branch `uiux-agent` (Phase 6). Reviewed on a production build (`next start`)
with the API mocked (`frontend/e2e/analysis.mock.py`, `frontend/e2e/interview.mock.py` and a
finished-analysis fixture), at 1280 px and 390 px, light and dark.

These pages were **not changed** on this branch because other agents own them
(`components/analysis-view.tsx`, `components/interview/**`, `app/session/**`). The design system
they should move to now exists:

| Need | Use |
|---|---|
| Colours | Semantic tokens in `app/globals.css`: `bg-surface`, `bg-surface-muted`, `bg-surface-sunken`, `border-border`, `text-fg`, `text-fg-muted`, `text-fg-subtle`, `text-link`, `bg-accent`, `bg-accent-soft`/`text-accent-soft-fg`, `success-*`, `warning-*`, `danger-*` (`-soft`, `-fg`, `-solid`). Dark mode is built in, so the `dark:` duplicates can go. |
| Focus ring | `focusRing` from `components/ui/cn.ts` (same 2px outline as `FOCUS_RING` in `interview/parts.tsx`, but token-based) |
| Buttons | `Button`, `ButtonLink`, `buttonClasses()` in `components/ui/button.tsx` (replace `BUTTON_PRIMARY` / `BUTTON_SECONDARY`) |
| Cards, badges | `Card` (`tone="default" / "raised" / "muted"`), `Badge` (`tone="success" / "warning" / "danger" / "accent" / "neutral"`) |
| Form controls | `Textarea`, `Input`, `Checkbox`, `Label`, `Hint`, `FieldError` in `components/ui/field.tsx` |
| Icons | `components/ui/icons.tsx` (inline SVG: `Check`, `Alert`, `Mic`, `ArrowRight`, ...) |
| Layout | `Container` (`size="narrow"` = `max-w-3xl`) in `components/ui/section.tsx` |

Screenshots: `docs/ux-review/`. They were taken just before the Phase 4 voice UI was merged, so the
voice recorder, mode switch and speech feedback card are not covered here; review them with
`frontend/e2e/voice.mock.py` screenshots after merging.

## Status (2026-11-12, branch `uxfix-agent`)

Items 1–14 and 16–19 are done; 15 is skipped (no data for it yet). Notes:
- 12: the footer is hidden on the interview via `data-focus-mode` + a `body:has()` rule in
  `globals.css`, not a route-group layout (smaller change, no layout move).
- 18: main's Phase 5 "See your report" CTA leads the completion screen.
- The report page (Phase 5, `app/session/[id]/report/page.tsx`) still has its own
  "← HireReady AI" link; left as main shipped it.
After screenshots (1280 light, 390 dark): `docs/ux-review/after/`.

## Priority 1 (do first: visible in the 30-second recruiter path)

1. **Done (uxfix-agent).** **Remove the "← HireReady AI" back links** on both pages
   (`app/session/[id]/analysis/page.tsx`, `app/session/[id]/interview/page.tsx`). The root layout
   now has a site header with the logo, so the link is a duplicate and, on the interview page, it is
   not aligned with the centered content (`interview-start-desktop.png`).
2. **Done (uxfix-agent).** **Put the main action at the top of a finished analysis.** "Start interview" only exists at the
   very bottom, after the full 7-day plan (`analysis-desktop-light.png`: about 3,000 px down). Add a
   compact summary row under the title: score, "3 strong · 1 weak · 1 gap", and a primary
   `ButtonLink` "Start mock interview". Keep the bottom CTA too.
3. **Done (uxfix-agent).** **Collapse the progress pills once the analysis is done.** Four green "✓" pills stay on screen
   forever and take ~100 px on mobile (2×2 grid, `analysis-mobile-dark.png`). When `done`, replace
   them with one muted line ("Analysis complete · re-opened from your session"), or hide them.
4. **Done (uxfix-agent).** **Stopped/failed analysis keeps pulsing skeletons** (`analysis-stopped-mobile-light.png`):
   after an error, sections that never arrived still show animated skeletons, which reads as
   "still loading". On `error`, render a static empty state ("Not available, try again") or hide
   the empty cards, and make "Try again" a real button (`Button variant="secondary"`), not an
   underlined text link.
5. **Done (uxfix-agent).** **Show the gaps first.** Must-have skills are listed in JD order, so strong skills push the
   actual gaps below the fold. Sort within each group: no evidence → weak → strong, and/or add
   filter chips ("Gaps (1) · Weak (1) · Strong (3)"). The gaps are what the user came for.
6. **Done (uxfix-agent).** **Make "verified in your CV" a visible trust signal.** It is 12 px grey text after the quote. Use
   the pattern from the landing preview (`components/landing/product-preview.tsx`): a small
   `text-success-fg` line with the `Check` icon. This is the product's differentiator; it should
   not look like a footnote.

## Priority 2 (polish, consistency)

7. **Done (uxfix-agent).** **Gauge colour and text.** `ScoreGauge` uses raw hex (`#059669`, `#d97706`, `#dc2626`) and the
   amber at 50–74 looks like a warning for a decent 72. Use the tokens (`stroke-success-solid`,
   `stroke-warning-solid`, `stroke-danger-solid`), consider indigo (`stroke-accent`) for the
   middle band, and add a verbal label under the number ("Good match", "Partial match",
   "Big gaps") so colour isn't the only signal (WCAG 1.4.1).
8. **Done (uxfix-agent).** **7-day plan is very long** (7 × tasks list + link, ~1,000 px on desktop). Use a 2-column grid
   on `lg`, or `<details>` per day with day 1 open. Mark external links: add an "opens in a new
   tab" `sr-only` suffix (they use `target="_blank"`) and an external-link icon.
9. **Done (uxfix-agent).** **Replace zinc/indigo literals with tokens** in `analysis-view.tsx` and `interview/parts.tsx`
   (e.g. `border-zinc-200 dark:border-zinc-800` → `border-border`, `text-zinc-500` →
   `text-fg-subtle`, `bg-indigo-600 hover:bg-indigo-700` → `buttonClasses()`). Behaviour stays
   the same; dark mode and contrast come for free. The tokens were chosen for AA contrast in both themes, so this also protects contrast as colours change.
10. **Done (uxfix-agent).** **Interview question caption** is a near-black block on white (`interview-follow-up-*.png`).
    Strong for captions, but heavy next to the rest of the UI. Consider `bg-surface-sunken
    text-fg` with a 4px `border-l-accent`, or keep dark but use `bg-zinc-900` in light mode only
    and `bg-surface-sunken` in dark mode (currently black-on-near-black in dark).
11. **Done (uxfix-agent).** **Transcript sidebar text is 12 px** on desktop. Use 14 px (`text-sm`) for the answers; the
    sidebar has room.
12. **Done (uxfix-agent).** **Interview page: focus mode.** The global footer now appears under the interview. On a phone
    it adds a long scroll below the answer box. Options: hide `SiteFooter` on `/session/*` (move
    header/footer into an `app/(marketing)/layout.tsx` route group and give `app/session` a slim
    layout with just the logo), or keep it but it's low priority.
13. **Done (uxfix-agent).** **Disabled "Send answer"** at 50% opacity on indigo is low contrast (`interview-follow-up-mobile.png`).
    The start form now uses `aria-disabled` + a hint line ("To continue, add …") instead of a
    silently disabled button; the same pattern works here ("Type at least a few words to send").
14. **Done (uxfix-agent).** **Switch screenshot check.** In `interview-start-desktop.png` the practice-mode switch was
    captured right after toggling and still looks "off" (track grey) while the text says "on".
    Most likely the 150 ms colour transition was mid-way; worth a quick manual check. In Tailwind
    v4 prefer `peer-checked:[&>span]:translate-x-5` (variant order is left to right) over the
    current `[&>span]:peer-checked:translate-x-5`, which only works because of how the selector
    happens to nest.

## Priority 3 (nice to have)

15. **Skipped:** the analysis API has no CV file name or created date; needs a backend field first. Analysis title: add the CV file name or "Sample CV" and the date under the role title, so a
    reloaded session is recognisable.
16. **Done (uxfix-agent).** "How is this calculated?" `<details>`: style the summary like the landing FAQ (custom marker,
    focus ring) and show the formula in `font-mono`.
17. **Done (uxfix-agent).** Strengths card: the empty state ("We couldn't find CV evidence…") could link to the prep plan
    section (`#plan`) instead of saying "below".
18. **Done (uxfix-agent).** Interview completion: once the report ships (Phase 5), the completion screen should lead with
    the report CTA; today "Back to your analysis" is the only action.
19. **Done (uxfix-agent).** Mobile interview: the keyboard hint ("Press Ctrl / ⌘ + Enter") is irrelevant on touch devices;
    hide it below `sm` or with `@media (pointer: coarse)`.

## What already works well

- Clear streamed progress with `aria-current="step"`, polite live regions and reduced-motion
  handling; skeletons have the same footprint as content (no layout shift).
- The interview never loses typed text (drafts survive reloads and errors), and 429/503/network
  errors are friendly and specific.
- Keyboard flow on the interview page is good: the answer box is focused on each new question,
  Ctrl/⌘+Enter sends, the transcript toggle has `aria-expanded`.
- Both mocked browser tests pass with the new global header/footer:
  `python e2e/interview.mock.py` and `python e2e/analysis.mock.py` (against `next start -p 3001`).
