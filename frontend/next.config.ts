import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV !== "production";

// Server-side only (no NEXT_PUBLIC_ prefix): the browser never sees the backend URL.
const BACKEND_URL = (process.env.BACKEND_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

// Baseline CSP without nonces, so the landing page can stay statically generated.
// Cloudflare Turnstile is allowed ONLY on the pages that create a session (`TURNSTILE_PAGES`):
// every other page (session, report, privacy, reminder links) can't load or frame it.
const TURNSTILE = "https://challenges.cloudflare.com";
function buildCsp(turnstile: boolean): string {
  const t = turnstile ? ` ${TURNSTILE}` : "";
  return [
    "default-src 'self'",
    `script-src 'self' 'unsafe-inline'${t}${isDev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' blob: data:",
    "font-src 'self'",
    "connect-src 'self'",
    "media-src 'self' blob:",
    turnstile ? `frame-src ${TURNSTILE}` : "frame-src 'none'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    // Only on Vercel (HTTPS); it would break plain-HTTP `next start` on localhost.
    ...(process.env.VERCEL ? ["upgrade-insecure-requests"] : []),
  ].join("; ");
}
const csp = buildCsp(false);
/** Pages with the "Start" form or the "Try with a sample CV" button (both create a session). */
const TURNSTILE_PAGES = ["/", "/start", "/r/:path*"];

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "DENY" },
  // Isolates our window from cross-origin popups/openers (Turnstile uses an iframe, not a popup).
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  {
    key: "Permissions-Policy",
    value: "microphone=(self), camera=(), geolocation=(), payment=(), usb=()",
  },
];

/** Sent on /r/* (asserted by e2e/report.mock.py). */
const sharedReportHeaders = [
  { key: "X-Robots-Tag", value: "noindex, nofollow, noarchive" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "Cache-Control", value: "private, no-store" },
];

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async headers() {
    return [
      { source: "/:path*", headers: securityHeaders },
      // Shared reports: the share token is in the URL. Later entries override earlier ones for
      // the same key, so these win over the site-wide Referrer-Policy.
      ...TURNSTILE_PAGES.map((source) => ({
        source,
        headers: [{ key: "Content-Security-Policy", value: buildCsp(true) }],
      })),
      { source: "/r/:path*", headers: sharedReportHeaders },
      // Reminder links carry a token in the URL, like shared reports.
      { source: "/reminders/:path*", headers: sharedReportHeaders },
      { source: "/unsubscribe/:path*", headers: sharedReportHeaders },
    ];
  },
  async rewrites() {
    // Browser calls same-origin /api/v1/*; Next.js proxies to FastAPI.
    return [{ source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` }];
  },
};

export default nextConfig;
