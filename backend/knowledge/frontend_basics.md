---
competency: frontend_basics
title: Frontend Basics
levels: [junior, mid]
---

# Frontend Basics

## What interviewers evaluate

- Semantic HTML, CSS layout (flexbox, grid), and responsive design.
- JavaScript fundamentals: async/await, promises, the event loop, DOM events.
- A component framework such as React: props, state, effects, and data fetching.
- Accessibility basics: labels, keyboard navigation, contrast.
- For mid level: performance (bundle size, rendering strategies), state management, testing.

## Question bank

### Junior

#### What is the difference between props and state in React?

**Strong answer includes:** props are inputs passed from a parent and are read-only in the child;
state is data a component owns and updates with a setter, causing a re-render; lift state up when
siblings need to share it.

**Common weak answers:** "Props are for passing data" with no mention of state ownership or re-render.

**Red flags:** mutates props or state directly.

#### How do you make a page responsive?

**Strong answer includes:** mobile-first CSS, flexible layouts with flexbox/grid, relative units,
media queries for breakpoints, responsive images, and the viewport meta tag; tests on real device
sizes.

**Common weak answers:** "Use Bootstrap."

**Red flags:** fixed pixel widths everywhere.

#### Why does accessibility matter, and what are quick wins?

**Strong answer includes:** many users rely on screen readers or keyboards; quick wins: semantic
elements (button, nav, main), labels for inputs, alt text, visible focus states, sufficient
contrast, and ARIA only when native elements are not enough.

**Common weak answers:** "It is for blind users" with no techniques.

**Red flags:** uses clickable divs for buttons without keyboard support.

### Mid

#### What does `useEffect` do and what are common mistakes?

**Strong answer includes:** runs side effects after render, such as subscriptions and fetches;
the dependency array controls when it re-runs; return a cleanup function to cancel requests or
stop media streams; common mistakes are missing dependencies, infinite loops from setting state,
and using effects for values that could be computed during render.

**Common weak answers:** "It runs code when the component loads."

**Red flags:** never cleans up listeners or timers.

#### How would you improve the load performance of a web page?

**Strong answer includes:** measure first (Lighthouse, Core Web Vitals: LCP, CLS, INP); reduce
JavaScript (code-splitting, lazy loading), optimize images and fonts, prerender static pages, cache
with a CDN, avoid layout shifts by reserving space.

**Common weak answers:** "Minify the code."

**Red flags:** optimizes without measuring.

## Scoring anchors

Example question: "A form on your site is hard to use with a keyboard. How do you fix it?"

### Score 1/5

"Add more colours so it is easier to see." Does not address keyboard use.

### Score 3/5

"Make sure tab order works and inputs have labels." Correct but incomplete.

### Score 5/5

"Use native inputs and a real button so they are focusable, connect labels with `for`/`id`, keep a
logical tab order, add visible focus styles, announce errors with `aria-live` and link them via
`aria-describedby`, and test by navigating with only the keyboard and a screen reader."
Concrete, standards-based, and verified.

## Resources

- [MDN Learn web development](https://developer.mozilla.org/en-US/docs/Learn_web_development): HTML, CSS, JS foundations.
- [React: Learn](https://react.dev/learn): official React guide.
- [Next.js Learn](https://nextjs.org/learn): official Next.js course.
- [web.dev Learn Accessibility](https://web.dev/learn/accessibility): practical accessibility course.
