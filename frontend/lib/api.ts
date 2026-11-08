import type { Analysis, AnalysisEvent, InterviewTurn, SessionOptions } from "./types";
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
): Promise<{ session_id: string }> {
  const res = await fetch(`${BASE}/sessions${demo ? "?demo=true" : ""}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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
      if (data) yield { event, data: JSON.parse(data) } as AnalysisEvent;
    }
  }
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
