// Small per-browser preferences (localStorage). Every access is wrapped: storage can be disabled
// (private mode, strict settings), and preferences are a nice-to-have, never required.

export type AnswerMode = "voice" | "text";

const SESSION_MODE_KEY = (id: string) => `hireready:mode:${id}`;
const TTS_MUTED_KEY = "hireready:tts-muted";

function read(key: string): string | null {
  try {
    return typeof window === "undefined" ? null : localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* ignore */
  }
}

/** The mode chosen on /start (or the one the user last switched to on the interview page). */
export function saveSessionMode(sessionId: string, mode: AnswerMode) {
  write(SESSION_MODE_KEY(sessionId), mode);
}

export function getSessionMode(sessionId: string): AnswerMode | null {
  const v = read(SESSION_MODE_KEY(sessionId));
  return v === "voice" || v === "text" ? v : null;
}

export function getTtsMuted(): boolean {
  return read(TTS_MUTED_KEY) === "1";
}

export function setTtsMuted(muted: boolean) {
  write(TTS_MUTED_KEY, muted ? "1" : "0");
}
