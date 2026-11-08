import { ApiError, authHeaders, parseError } from "./api";
import type { InterviewTurn, SpeechMetrics } from "./types";
import type { Recording } from "./use-recorder";

function extensionFor(mime: string): string {
  if (mime.includes("mp4") || mime.includes("aac")) return "m4a";
  if (mime.includes("ogg")) return "ogg";
  if (mime.includes("wav")) return "wav";
  if (mime.includes("mpeg")) return "mp3";
  return "webm";
}

/**
 * Upload a recorded answer (multipart: question_id + audio) and get the next turn.
 * XMLHttpRequest instead of fetch because fetch has no upload progress events.
 * `onProgress(fraction)` goes 0..1 while uploading; then the server transcribes and scores.
 */
export function submitVoiceAnswer(
  sessionId: string,
  questionId: string,
  recording: Recording,
  onProgress?: (fraction: number) => void,
): Promise<InterviewTurn> {
  const form = new FormData();
  form.append("question_id", questionId);
  form.append("audio", recording.blob, `answer.${extensionFor(recording.mimeType)}`);
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/v1/sessions/${sessionId}/interview/answer`);
    for (const [k, v] of Object.entries(authHeaders(sessionId) as Record<string, string>))
      xhr.setRequestHeader(k, v);
    xhr.responseType = "text";
    xhr.timeout = 90_000;
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
    };
    xhr.upload.onload = () => onProgress?.(1);
    xhr.onload = async () => {
      const headers = new Headers();
      const ct = xhr.getResponseHeader("Content-Type");
      const ra = xhr.getResponseHeader("Retry-After");
      if (ct) headers.set("Content-Type", ct);
      if (ra) headers.set("Retry-After", ra);
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as InterviewTurn);
        } catch {
          reject(new ApiError("bad_response", "Unexpected response from the server.", 502));
        }
        return;
      }
      reject(await parseError(new Response(xhr.responseText, { status: xhr.status, headers })));
    };
    xhr.onerror = () => reject(new TypeError("network error"));
    xhr.ontimeout = () => reject(new TypeError("timeout"));
    xhr.send(form);
  });
}

// ------------------------------------------------------------------ speech metrics guidance

export type Guidance = { label: string; value: string; tone: "good" | "warn"; advice: string };

/** Plain-language feedback on pace, fillers and pauses (shown in practice mode). */
export function speechGuidance(m: SpeechMetrics): Guidance[] {
  const out: Guidance[] = [];
  const wpm = m.words_per_minute;
  if (wpm !== null) {
    const rounded = Math.round(wpm);
    const ok = wpm >= 120 && wpm <= 160;
    out.push({
      label: "Pace",
      value: `${rounded} words per minute`,
      tone: ok || (wpm >= 110 && wpm <= 170) ? "good" : "warn",
      advice: ok
        ? "Great pace. Ideal pace is roughly 120–160 WPM."
        : wpm < 120
          ? "A little slow. Ideal pace is roughly 120–160 WPM; try shorter sentences and fewer restarts."
          : "A little fast. Ideal pace is roughly 120–160 WPM; pause briefly after each key point.",
    });
  }
  const minutes = Math.max((m.speaking_seconds ?? m.duration_seconds ?? 0) / 60, 0.25);
  const perMinute = m.filler_count / minutes;
  const top = Object.entries(m.filler_breakdown)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([w, n]) => `“${w}” ×${n}`)
    .join(", ");
  out.push({
    label: "Filler words",
    value: m.filler_count === 0 ? "None" : `${m.filler_count}${top ? ` (${top})` : ""}`,
    tone: perMinute <= 3 ? "good" : "warn",
    advice:
      m.filler_count === 0
        ? "Clean delivery with no filler words."
        : perMinute <= 3
          ? "A few fillers are natural. Under about 3 per minute sounds polished."
          : "Try replacing fillers with a short silent pause: it sounds more confident than “um”.",
  });
  out.push({
    label: "Long pauses",
    value:
      m.long_pauses === 0
        ? "None over 2 seconds"
        : `${m.long_pauses} over 2 seconds (longest ${m.longest_pause_seconds.toFixed(1)} s)`,
    tone: m.long_pauses <= 1 ? "good" : "warn",
    advice:
      m.long_pauses <= 1
        ? "Short pauses to think are fine and sound natural."
        : "If you need time, say so (“Let me think about that for a second”) instead of going silent.",
  });
  return out;
}
