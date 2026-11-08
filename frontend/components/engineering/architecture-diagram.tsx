// Architecture diagram in plain HTML/CSS. The SPEC suggested Mermaid, but Mermaid renders in the
// browser from a ~600 KB script (a CDN is blocked by our CSP, and bundling it would dwarf the
// rest of the page). This version is static HTML: zero JS, selectable text, readable by screen
// readers as nested lists, responsive, and it follows the light/dark theme.
import { cn } from "@/components/ui/cn";

type Node = { name: string; detail: string };
type Tier = { label: string; where: string; tone: string; nodes: Node[] };

const TIERS: Tier[] = [
  {
    label: "Browser",
    where: "Your device",
    tone: "border-border-strong",
    nodes: [
      { name: "Landing & engineering pages", detail: "Prerendered HTML, no data fetching" },
      { name: "/start", detail: "CV dropzone and job description form" },
      { name: "Analysis page", detail: "Reads the SSE stream with fetch, renders each section" },
      { name: "Interview page", detail: "One turn per request; draft kept on reload" },
    ],
  },
  {
    label: "Next.js 16 on Vercel",
    where: "Same origin",
    tone: "border-accent/50",
    nodes: [
      { name: "Static + partial prerender", detail: "Cache Components; shells served from CDN" },
      { name: "Security headers", detail: "CSP, HSTS, Permissions-Policy (microphone=self)" },
      { name: "/api/* rewrite", detail: "Browser never sees the backend URL; no CORS needed" },
    ],
  },
  {
    label: "FastAPI on Vercel (Python 3.12)",
    where: "Serverless functions",
    tone: "border-accent/50",
    nodes: [
      {
        name: "Guards",
        detail: "Hashed guest token, per-session quotas, rate-limit + Turnstile hooks",
      },
      { name: "Intake", detail: "Size, MIME, magic bytes, page cap; only text is kept" },
      { name: "Gap analysis", detail: "Extraction, hybrid retrieval, judge, quote check, score" },
      { name: "Interviewer", detail: "LangGraph, one turn per request, state saved as JSON" },
    ],
  },
  {
    label: "Data and AI providers",
    where: "Managed services",
    tone: "border-border-strong",
    nodes: [
      { name: "Supabase Postgres + pgvector", detail: "RLS on every table; hybrid_search (RRF)" },
      {
        name: "Groq",
        detail: "gpt-oss-20b (fast), gpt-oss-120b (strong); Whisper for voice (in progress)",
      },
      { name: "Google Gemini", detail: "768-d embeddings; fallback text model" },
    ],
  },
];

const ARROWS = [
  "HTTPS, same-origin /api/v1",
  "Rewrite to the FastAPI function",
  "SQL over REST (service role) and LLM APIs over httpx",
];

export function ArchitectureDiagram() {
  return (
    <figure className="space-y-4">
      <ol className="space-y-0" aria-label="Request path, from the browser to the data layer">
        {TIERS.map((t, i) => (
          <li key={t.label}>
            <div className={cn("bg-surface rounded-2xl border-2 p-4 sm:p-5", t.tone)}>
              <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="font-semibold">{t.label}</h3>
                <span className="text-fg-subtle text-xs font-medium tracking-wide uppercase">
                  {t.where}
                </span>
              </div>
              <ul
                className={cn(
                  "grid gap-2 sm:grid-cols-2",
                  t.nodes.length === 4 ? "lg:grid-cols-4" : "lg:grid-cols-3",
                )}
              >
                {t.nodes.map((n) => (
                  <li key={n.name} className="bg-surface-sunken rounded-xl px-3 py-2.5">
                    <p className="text-sm font-medium">{n.name}</p>
                    <p className="text-fg-muted mt-0.5 text-xs">{n.detail}</p>
                  </li>
                ))}
              </ul>
            </div>
            {i < ARROWS.length && (
              <div className="flex items-center gap-3 py-2 pl-6 sm:pl-10">
                <svg
                  viewBox="0 0 12 32"
                  className="text-fg-subtle h-8 w-3 shrink-0"
                  aria-hidden="true"
                >
                  <path
                    d="M6 0v28M1.5 23.5L6 29l4.5-5.5"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                <span className="text-fg-muted text-xs">{ARROWS[i]}</span>
              </div>
            )}
          </li>
        ))}
      </ol>
      <figcaption className="text-fg-subtle text-sm">
        Request path. The browser only talks to its own origin; only the backend holds API keys and
        the database service role.
      </figcaption>
    </figure>
  );
}
