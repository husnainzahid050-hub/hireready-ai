import type {
  Analysis,
  AnalysisEvent,
  InterviewTurn,
  ReportEvent,
  ReportResponse,
  SessionOptions,
  SharedReportResponse,
  ShareInfo,
} from "./types";
import { saveSessionMode } from "./prefs";

const BASE = "/api/v1";
const TOKEN_KEY = (id: string) => `hireready:token:${id}`;

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    /** Seconds to wait before retrying (from the Retry-After header on 429). */
    public retryAfter: number | null = null,
  ) {
    super(message);
  }
}

// The guest token proves ownership of a session. It lives only in this browser.
export function saveToken(sessionId: string, token: string) {
  localStorage.setItem(TOKEN_KEY(sessionId), token);
}

export function getToken(sessionId: string): string | null {
  return typeof window === "undefined" ? null : localStorage.getItem(TOKEN_KEY(sessionId));
}

function retryAfterSeconds(res: Response): number | null {
  const raw = res.headers.get("Retry-After");
  if (!raw) return null;
  const secs = Number(raw);
  if (Number.isFinite(secs)) return Math.max(0, Math.ceil(secs));
  const date = Date.parse(raw); // HTTP-date form
  return Number.isNaN(date) ? null : Math.max(0, Math.ceil((date - Date.now()) / 1000));
}

export async function parseError(res: Response): Promise<ApiError> {
  const retryAfter = res.status === 429 ? retryAfterSeconds(res) : null;
  try {
    const body = (await res.json()) as { error?: { code: string; message: string } };
    if (body.error)
      return new ApiError(body.error.code, body.error.message, res.status, retryAfter);
  } catch {
    /* not JSON */
  }
  if (res.status === 413) return new ApiError("too_large", "That file is too large.", 413);
  if (res.status === 429)
    return new ApiError("rate_limited", "Too many requests. Please wait.", 429, retryAfter);
  return new ApiError("http_error", "Something went wrong. Please try again.", res.status);
}

export function authHeaders(sessionId: string): HeadersInit {
  const token = getToken(sessionId);
  return token ? { "X-Guest-Token": token } : {};
}

export async function createSession(
  options: SessionOptions,
  demo = false,
  turnstileToken: string | null = null,
): Promise<{ session_id: string }> {
  const res = await fetch(`${BASE}/sessions${demo ? "?demo=true" : ""}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      // Single-use bot-check token (lib/turnstile.ts); omitted while Turnstile is off.
      ...(turnstileToken ? { "X-Turnstile-Token": turnstileToken } : {}),
    },
    body: JSON.stringify(options),
  });
  if (!res.ok) throw await parseError(res);
  const data = (await res.json()) as { session_id: string; guest_token: string };
  saveToken(data.session_id, data.guest_token);
  saveSessionMode(data.session_id, options.mode); // the interview page's default answer mode
  return { session_id: data.session_id };
}

export async function uploadDocuments(sessionId: string, cv: File, jdText: string) {
  const form = new FormData();
  form.append("cv", cv);
  form.append("jd_text", jdText);
  const res = await fetch(`${BASE}/sessions/${sessionId}/documents`, {
    method: "POST",
    headers: authHeaders(sessionId),
    body: form,
  });
  if (!res.ok) throw await parseError(res);
}

export async function getAnalysis(sessionId: string): Promise<Analysis | null> {
  const res = await fetch(`${BASE}/sessions/${sessionId}/analysis`, {
    headers: authHeaders(sessionId),
    cache: "no-store",
  });
  if (!res.ok) throw await parseError(res);
  return ((await res.json()) as { analysis: Analysis | null }).analysis;
}

/** Parse `event:` / `data:` blocks from an SSE response body. */
async function* readEvents<T>(res: Response): AsyncGenerator<T> {
  if (!res.body) return;
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      let event = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (data) yield { event, data: JSON.parse(data) } as T;
    }
  }
}

/**
 * Stream the analysis as Server-Sent Events. EventSource only supports GET without headers,
 * so we POST with fetch and parse the `event:` / `data:` lines from the response stream.
 */
export async function* streamAnalysis(
  sessionId: string,
  signal?: AbortSignal,
): AsyncGenerator<AnalysisEvent> {
  const res = await fetch(`${BASE}/sessions/${sessionId}/analyze`, {
    method: "POST",
    headers: authHeaders(sessionId),
    signal,
  });
  if (!res.ok || !res.body) throw await parseError(res);
  yield* readEvents<AnalysisEvent>(res);
}

// ------------------------------------------------------------------ interview (Phase 3)

async function interviewRequest(
  sessionId: string,
  path: "" | "/start" | "/answer",
  body?: unknown,
): Promise<InterviewTurn> {
  const res = await fetch(`${BASE}/sessions/${sessionId}/interview${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      ...authHeaders(sessionId),
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as InterviewTurn;
}

/** Current interview state with full history (resume after reload). 409 `not_started` if none. */
export function getInterview(sessionId: string): Promise<InterviewTurn> {
  return interviewRequest(sessionId, "");
}

/** Plan the interview and return the first question. Idempotent on the server. */
export function startInterview(sessionId: string, practiceMode: boolean): Promise<InterviewTurn> {
  return interviewRequest(sessionId, "/start", { practice_mode: practiceMode });
}

export const ANSWER_MAX = 5000;

/** Submit a text answer for the current question; returns the next turn. */
export function submitAnswer(
  sessionId: string,
  questionId: string,
  text: string,
): Promise<InterviewTurn> {
  return interviewRequest(sessionId, "/answer", { question_id: questionId, text });
}

// ------------------------------------------------------------------ report (Phase 5)

async function sessionJson<T>(
  sessionId: string,
  path: string,
  init: { method?: string; body?: unknown } = {},
): Promise<T> {
  const res = await fetch(`${BASE}/sessions/${sessionId}${path}`, {
    method: init.method ?? "GET",
    headers: {
      ...authHeaders(sessionId),
      ...(init.body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
    cache: "no-store",
  });
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as T;
}

/** Saved report + share / email state. 409 `interview_not_completed` before the interview ends. */
export function getReport(sessionId: string): Promise<ReportResponse> {
  return sessionJson<ReportResponse>(sessionId, "/report");
}

/** Build the report (SSE: status → overview → done). A cached report comes back as one `done`. */
export async function* streamReport(
  sessionId: string,
  signal?: AbortSignal,
): AsyncGenerator<ReportEvent> {
  const res = await fetch(`${BASE}/sessions/${sessionId}/report`, {
    method: "POST",
    headers: authHeaders(sessionId),
    signal,
  });
  if (!res.ok || !res.body) throw await parseError(res);
  yield* readEvents<ReportEvent>(res);
}

export function setShareLink(sessionId: string, action: "create" | "revoke"): Promise<ShareInfo> {
  return sessionJson<ShareInfo>(sessionId, "/report/share", { method: "POST", body: { action } });
}

/** Email the report summary. 503 `email_not_configured` when the server has no provider. */
export function emailReport(
  sessionId: string,
  email: string | null,
): Promise<{ sent: boolean; emailed_at: string; sent_to: string }> {
  return sessionJson(sessionId, "/email", { method: "POST", body: email ? { email } : {} });
}

/**
 * Opt in to daily 7-day-plan reminders (double opt-in: the server sends one confirmation email).
 * `exists` = this session already has a reminder. Errors: 400 `email_required`,
 * 409 `report_not_ready` / `no_plan`, 429 `rate_limited`, 502 `email_failed`,
 * 503 `reminders_not_configured`.
 */
export function subscribeReminders(
  sessionId: string,
  email: string | null,
): Promise<{ status: "pending" | "exists" }> {
  return sessionJson(sessionId, "/reminders", { method: "POST", body: email ? { email } : {} });
}

/** Delete the session and everything in it; forgets the guest token in this browser. */
export async function deleteSession(sessionId: string): Promise<void> {
  const res = await fetch(`${BASE}/sessions/${sessionId}`, {
    method: "DELETE",
    headers: authHeaders(sessionId),
  });
  if (!res.ok && res.status !== 404) throw await parseError(res);
  try {
    localStorage.removeItem(TOKEN_KEY(sessionId));
  } catch {
    /* storage blocked: nothing to forget */
  }
}

/** Public read-only report behind a share token (no guest token needed). */
export async function getSharedReport(token: string): Promise<SharedReportResponse> {
  const res = await fetch(`${BASE}/reports/shared/${encodeURIComponent(token)}`, {
    cache: "no-store",
    referrerPolicy: "no-referrer",
  });
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as SharedReportResponse;
}

// ------------------------------------------------------------------ reminders (Phase 7)

export type ReminderStatus = {
  status: "pending" | "active" | "paused" | "finished";
  day: number;
  days_total: number;
  last_done_day: number;
  role_title: string;
  plan: { day: number; focus: string }[];
};

/** Token-only calls from reminder emails: no guest token, never sent as a Referer. */
async function reminderCall<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
    referrerPolicy: "no-referrer",
  });
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as T;
}

const enc = encodeURIComponent;

export function getReminder(token: string): Promise<ReminderStatus> {
  return reminderCall(`/reminders/${enc(token)}`);
}

export function reminderAction(
  token: string,
  action: "confirm" | "done" | "resume",
  day?: number,
): Promise<ReminderStatus> {
  return reminderCall(
    `/reminders/${enc(token)}/${action}`,
    "POST",
    action === "done" ? { day } : undefined,
  );
}

export function unsubscribeStatus(token: string): Promise<{ subscribed: boolean }> {
  return reminderCall(`/unsubscribe/${enc(token)}`);
}

export function unsubscribe(token: string): Promise<{ unsubscribed: boolean }> {
  return reminderCall(`/unsubscribe/${enc(token)}`, "POST");
}
