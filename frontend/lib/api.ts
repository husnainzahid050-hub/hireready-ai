import type { Analysis, AnalysisEvent, SessionOptions } from "./types";

const BASE = "/api/v1";
const TOKEN_KEY = (id: string) => `hireready:token:${id}`;

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
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

async function parseError(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as { error?: { code: string; message: string } };
    if (body.error) return new ApiError(body.error.code, body.error.message, res.status);
  } catch {
    /* not JSON */
  }
  if (res.status === 413) return new ApiError("too_large", "That file is too large.", 413);
  return new ApiError("http_error", "Something went wrong. Please try again.", res.status);
}

function authHeaders(sessionId: string): HeadersInit {
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
