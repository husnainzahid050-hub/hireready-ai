"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/** Server limits (backend/app/services/stt.py). Checked here first so we never upload junk. */
export const MAX_RECORDING_SECONDS = 120;
export const MAX_AUDIO_BYTES = 3_000_000;
const MIN_RECORDING_SECONDS = 1;
// ~48 kbit/s opus: clear speech, and 120 s is only ~0.7 MB.
const AUDIO_BITS_PER_SECOND = 48_000;

// Chrome / Firefox / Edge record webm+opus; Safari records mp4 (AAC). First supported wins.
const MIME_CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4;codecs=mp4a.40.2",
  "audio/mp4",
  "audio/ogg;codecs=opus",
];

export type RecorderError =
  | "unsupported" // no MediaRecorder / getUserMedia
  | "insecure" // page not served over HTTPS
  | "denied" // the user (or a browser policy) blocked the microphone
  | "no_device" // no microphone plugged in
  | "busy" // another app holds the microphone
  | "too_short"
  | "too_large"
  | "unknown";

export type RecorderStatus = "idle" | "requesting" | "recording" | "stopped";

export type Recording = { blob: Blob; mimeType: string; seconds: number };

export const RECORDER_ERROR_TEXT: Record<RecorderError, string> = {
  unsupported:
    "This browser can't record audio. You can type your answers instead, or try a recent Chrome, Edge, Firefox or Safari.",
  insecure: "Voice recording needs a secure (https) connection. You can type your answers instead.",
  denied:
    "Microphone access is blocked. Allow it in your browser's site settings (the icon next to the address bar), or type your answers instead.",
  no_device: "We couldn't find a microphone. Plug one in and try again, or type your answers.",
  busy: "Your microphone is being used by another app. Close it and try again, or type your answers.",
  too_short: "That recording was too short. Tap the button and answer, then tap again to stop.",
  too_large: "That recording is too large to upload. Please give a shorter answer.",
  unknown: "Recording didn't work. Please try again, or type your answer instead.",
};

/** Can this browser record at all? (Safe to call during render on the client only.) */
export function recordingSupport(): RecorderError | null {
  if (typeof window === "undefined") return "unsupported";
  if (!window.isSecureContext) return "insecure";
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined")
    return "unsupported";
  return null;
}

export function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined" || !MediaRecorder.isTypeSupported) return undefined;
  return MIME_CANDIDATES.find((t) => MediaRecorder.isTypeSupported(t));
}

function errorFromException(e: unknown): RecorderError {
  const name = e instanceof DOMException || e instanceof Error ? e.name : "";
  if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError")
    return "denied";
  if (
    name === "NotFoundError" ||
    name === "OverconstrainedError" ||
    name === "DevicesNotFoundError"
  )
    return "no_device";
  if (name === "NotReadableError" || name === "AbortError" || name === "TrackStartError")
    return "busy";
  return "unknown";
}

type Live = {
  stream: MediaStream;
  recorder: MediaRecorder;
  chunks: Blob[];
  startedAt: number;
  audio: AudioContext | null;
  raf: number | null;
  timer: number | null;
  discard: boolean; // unmount / reset: drop the data instead of producing a Recording
};

/**
 * Tap-to-start / tap-to-stop recorder with a timer, a level meter and hard cleanup.
 *
 * - `meterRef`: attach to an element; its `--level` CSS variable (0..1) is updated from an
 *   AnalyserNode in a requestAnimationFrame loop, WITHOUT React re-renders. With
 *   prefers-reduced-motion the loop updates ~4x/second instead of every frame.
 * - Media tracks, the AudioContext, the rAF loop and the timer are always released on stop,
 *   on error and on unmount, so the browser's "recording" indicator never stays on.
 */
export function useRecorder({ maxSeconds = MAX_RECORDING_SECONDS } = {}) {
  const [status, setStatus] = useState<RecorderStatus>("idle");
  const [error, setError] = useState<RecorderError | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [recording, setRecording] = useState<Recording | null>(null);
  const live = useRef<Live | null>(null);
  const requestId = useRef(0); // invalidates a pending getUserMedia when the user cancels
  const meterRef = useRef<HTMLDivElement | null>(null);

  const release = useCallback((l: Live) => {
    if (l.raf !== null) cancelAnimationFrame(l.raf);
    if (l.timer !== null) window.clearInterval(l.timer);
    l.raf = null;
    l.timer = null;
    l.stream.getTracks().forEach((t) => t.stop());
    if (l.audio && l.audio.state !== "closed") void l.audio.close().catch(() => undefined);
    l.audio = null;
    meterRef.current?.style.setProperty("--level", "0");
  }, []);

  const stop = useCallback(() => {
    const l = live.current;
    if (!l) {
      // Tapped "stop" while the permission prompt was still open: cancel that request.
      requestId.current += 1;
      setStatus((s) => (s === "requesting" ? "idle" : s));
      return;
    }
    if (l.recorder.state !== "inactive")
      l.recorder.stop(); // -> onstop builds the Recording
    else release(l);
  }, [release]);

  const startMeter = useCallback((l: Live) => {
    const Ctx: typeof AudioContext | undefined =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return;
    try {
      const audio = new Ctx();
      const source = audio.createMediaStreamSource(l.stream);
      const analyser = audio.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser); // not connected to the speakers: no echo
      l.audio = audio;
      const data = new Uint8Array(analyser.fftSize);
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      let last = 0;
      const tick = (t: number) => {
        if (live.current !== l) return;
        l.raf = requestAnimationFrame(tick);
        if (reduce && t - last < 250) return;
        last = t;
        analyser.getByteTimeDomainData(data);
        let sum = 0;
        for (const v of data) sum += ((v - 128) / 128) ** 2;
        const rms = Math.sqrt(sum / data.length);
        const level = Math.min(1, rms * 4); // speech RMS is ~0.02-0.25
        meterRef.current?.style.setProperty("--level", level.toFixed(3));
      };
      l.raf = requestAnimationFrame(tick);
    } catch {
      /* the meter is decoration: recording still works without it */
    }
  }, []);

  const start = useCallback(async () => {
    if (live.current) return;
    const unsupported = recordingSupport();
    if (unsupported) {
      setError(unsupported);
      return;
    }
    const id = ++requestId.current;
    setError(null);
    setRecording(null);
    setElapsed(0);
    setStatus("requesting");
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
      });
    } catch (e) {
      if (id !== requestId.current) return;
      setError(errorFromException(e));
      setStatus("idle");
      return;
    }
    if (id !== requestId.current) {
      stream.getTracks().forEach((t) => t.stop()); // cancelled or unmounted meanwhile
      return;
    }
    let recorder: MediaRecorder;
    try {
      const mimeType = pickMimeType();
      recorder = new MediaRecorder(stream, {
        ...(mimeType ? { mimeType } : {}),
        audioBitsPerSecond: AUDIO_BITS_PER_SECOND,
      });
    } catch {
      stream.getTracks().forEach((t) => t.stop());
      setError("unsupported");
      setStatus("idle");
      return;
    }
    const l: Live = {
      stream,
      recorder,
      chunks: [],
      startedAt: performance.now(),
      audio: null,
      raf: null,
      timer: null,
      discard: false,
    };
    live.current = l;
    recorder.ondataavailable = (ev) => {
      if (ev.data.size) l.chunks.push(ev.data);
    };
    recorder.onerror = () => {
      l.discard = true;
      release(l);
      if (live.current === l) live.current = null;
      setError("unknown");
      setStatus("idle");
    };
    recorder.onstop = () => {
      const seconds = (performance.now() - l.startedAt) / 1000;
      release(l);
      if (live.current === l) live.current = null;
      if (l.discard) return;
      const mimeType = recorder.mimeType || l.chunks[0]?.type || "audio/webm";
      const blob = new Blob(l.chunks, { type: mimeType });
      l.chunks = [];
      setElapsed(Math.min(maxSeconds, seconds));
      if (seconds < MIN_RECORDING_SECONDS || blob.size < 1000) {
        setError("too_short");
        setStatus("idle");
      } else if (blob.size > MAX_AUDIO_BYTES) {
        setError("too_large");
        setStatus("idle");
      } else {
        setRecording({ blob, mimeType, seconds: Math.min(maxSeconds, seconds) });
        setStatus("stopped");
      }
    };
    // Track ending on its own (mic unplugged, permission revoked mid-answer): stop cleanly.
    stream.getAudioTracks().forEach((t) => (t.onended = () => stop()));
    recorder.start(1000); // 1 s chunks: a crash mid-answer still leaves most of the data
    l.timer = window.setInterval(() => {
      const s = (performance.now() - l.startedAt) / 1000;
      setElapsed(Math.min(maxSeconds, s));
      if (s >= maxSeconds) stop(); // hard cap, matches the server's 120 s limit
    }, 200);
    startMeter(l);
    setStatus("recording");
  }, [maxSeconds, release, startMeter, stop]);

  /** Forget the current recording / error (e.g. "record again"). */
  const reset = useCallback(() => {
    const l = live.current;
    if (l) {
      l.discard = true;
      if (l.recorder.state !== "inactive") l.recorder.stop();
      release(l);
      live.current = null;
    }
    requestId.current += 1;
    setRecording(null);
    setError(null);
    setElapsed(0);
    setStatus("idle");
  }, [release]);

  // Unmount (navigation, switching to text mode): never leave the microphone on.
  useEffect(
    () => () => {
      requestId.current += 1;
      const l = live.current;
      if (!l) return;
      l.discard = true;
      if (l.recorder.state !== "inactive") l.recorder.stop();
      release(l);
      live.current = null;
    },
    [release],
  );

  return { status, error, elapsed, recording, start, stop, reset, meterRef, maxSeconds };
}

export function formatClock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
