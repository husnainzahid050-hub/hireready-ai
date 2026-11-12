/**
 * Cloudflare Turnstile (bot check on session creation, SPEC 9).
 *
 * Off when NEXT_PUBLIC_TURNSTILE_SITE_KEY is unset (local dev, e2e mocks): `turnstileEnabled` is
 * false, nothing is loaded and no header is sent. The backend skips its check while
 * TURNSTILE_SECRET_KEY is unset too. Set BOTH or neither.
 *
 * The script is loaded on demand (explicit rendering), only on pages whose CSP allows
 * https://challenges.cloudflare.com (next.config.ts, TURNSTILE_PAGES), so the static landing
 * page pays nothing until someone clicks "Try with a sample CV".
 * API: https://developers.cloudflare.com/turnstile/get-started/client-side-rendering/
 */

export const TURNSTILE_SITE_KEY = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ?? "";
export const turnstileEnabled = TURNSTILE_SITE_KEY.length > 0;

const SCRIPT_URL = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";

type RenderOptions = {
  sitekey: string;
  action?: string;
  appearance?: "always" | "execute" | "interaction-only";
  callback?: (token: string) => void;
  "error-callback"?: () => void;
  "expired-callback"?: () => void;
};

export type TurnstileApi = {
  render: (container: HTMLElement, options: RenderOptions) => string;
  reset: (widgetId: string) => void;
  remove: (widgetId: string) => void;
};

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

let loading: Promise<TurnstileApi> | null = null;

export function loadTurnstile(): Promise<TurnstileApi> {
  if (typeof window === "undefined") return Promise.reject(new Error("no window"));
  if (window.turnstile) return Promise.resolve(window.turnstile);
  if (!loading) {
    loading = new Promise<TurnstileApi>((resolve, reject) => {
      const script = document.createElement("script");
      script.src = SCRIPT_URL;
      script.async = true;
      script.onload = () =>
        window.turnstile ? resolve(window.turnstile) : reject(new Error("turnstile missing"));
      script.onerror = () => {
        loading = null;
        reject(new Error("turnstile failed to load"));
      };
      document.head.appendChild(script);
    });
  }
  return loading;
}

/**
 * Render a widget into `container` and resolve with a fresh, single-use token. With
 * `interaction-only` the widget stays invisible unless Cloudflare needs the person to click.
 * The widget is removed afterwards, so every call gets a new token.
 */
export async function getTurnstileToken(
  container: HTMLElement,
  appearance: RenderOptions["appearance"] = "interaction-only",
  action = "session_create",
): Promise<string> {
  const api = await loadTurnstile();
  return new Promise<string>((resolve, reject) => {
    let id = "";
    const done = (fn: () => void) => {
      fn();
      if (id) api.remove(id);
    };
    id = api.render(container, {
      sitekey: TURNSTILE_SITE_KEY,
      action,
      appearance,
      callback: (token) => done(() => resolve(token)),
      "error-callback": () => done(() => reject(new Error("turnstile error"))),
      "expired-callback": () => done(() => reject(new Error("turnstile expired"))),
    });
  });
}

export const TURNSTILE_FAILED_MESSAGE =
  "We couldn't verify you're human. Please check your connection and try again.";
