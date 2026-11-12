import { NextResponse, type NextRequest } from "next/server";

/**
 * Forwards the browser's IP to the backend for per-IP rate limits (docs/SECURITY.md).
 *
 * The `/api/*` rewrite in next.config.ts calls the backend's own Vercel deployment from Vercel's
 * network, so the backend's platform headers describe that hop, not the browser. Here, on the
 * frontend request, Vercel has set `x-forwarded-for` / `x-real-ip` to the real client (and
 * overwrites anything the client sent). We copy it into `X-HireReady-Client-IP` plus a shared
 * secret the backend checks in constant time, so a direct caller of the backend URL can't choose
 * its own IP. Both headers are always overwritten, never passed through from the browser.
 *
 * `CLIENT_IP_HEADER_SECRET` is server-only (no NEXT_PUBLIC_ prefix). Unset: nothing is added and
 * the backend falls back to the platform headers.
 */
export function proxy(request: NextRequest) {
  const headers = new Headers(request.headers);
  headers.delete("x-hireready-client-ip");
  headers.delete("x-hireready-proxy-secret");
  const secret = process.env.CLIENT_IP_HEADER_SECRET;
  const ip =
    request.headers.get("x-real-ip") ??
    request.headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  if (secret && ip) {
    headers.set("x-hireready-client-ip", ip.slice(0, 64));
    headers.set("x-hireready-proxy-secret", secret);
  }
  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: "/api/:path*",
};
