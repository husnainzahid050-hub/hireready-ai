"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

import { getTtsMuted, setTtsMuted } from "./prefs";

// Mute preference as an external store, so every component reads the same persisted value and
// the server render (always "not muted") never mismatches hydration.
const muteListeners = new Set<() => void>();
function subscribeMuted(cb: () => void) {
  muteListeners.add(cb);
  return () => muteListeners.delete(cb);
}
function writeMuted(muted: boolean) {
  setTtsMuted(muted);
  muteListeners.forEach((cb) => cb());
}

/** English voice: prefer a local en-US/en-GB voice (no network, starts faster), then any en-*. */
export function pickVoice(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  const en = voices.filter((v) => v.lang?.toLowerCase().startsWith("en"));
  const score = (v: SpeechSynthesisVoice) =>
    (/^en[-_](us|gb)$/i.test(v.lang) ? 4 : 0) + (v.localService ? 2 : 0) + (v.default ? 1 : 0);
  return en.sort((a, b) => score(b) - score(a))[0] ?? null;
}

function synth(): SpeechSynthesis | null {
  return typeof window !== "undefined" && "speechSynthesis" in window
    ? window.speechSynthesis
    : null;
}

/**
 * Text-to-speech for the interviewer's questions (Web Speech API, runs in the browser: free,
 * no audio leaves the device). Captions are always on screen; this only adds the voice.
 * Speech is cancelled on unmount, on page hide, and whenever the caller calls `cancel()`
 * (e.g. when the user starts recording).
 */
export function useSpeech() {
  const supported = useSyncExternalStore(
    () => () => undefined,
    () => synth() !== null,
    () => false,
  );
  const muted = useSyncExternalStore(subscribeMuted, getTtsMuted, () => false);
  const [speaking, setSpeaking] = useState(false);
  const voice = useRef<SpeechSynthesisVoice | null>(null);
  const current = useRef<SpeechSynthesisUtterance | null>(null);

  useEffect(() => {
    const s = synth();
    if (!s) return;
    const load = () => {
      voice.current = pickVoice(s.getVoices());
    };
    load();
    s.addEventListener?.("voiceschanged", load); // Chrome loads voices asynchronously
    const onHide = () => {
      if (document.visibilityState === "hidden") s.cancel();
    };
    const onPageHide = () => s.cancel();
    document.addEventListener("visibilitychange", onHide);
    window.addEventListener("pagehide", onPageHide);
    return () => {
      s.removeEventListener?.("voiceschanged", load);
      document.removeEventListener("visibilitychange", onHide);
      window.removeEventListener("pagehide", onPageHide);
      current.current = null;
      s.cancel();
    };
  }, []);

  const cancel = useCallback(() => {
    current.current = null;
    synth()?.cancel();
    setSpeaking(false);
  }, []);

  /** Speak `text` (replacing anything being said). No-op when muted unless `force`. */
  const speak = useCallback((text: string, { force = false } = {}) => {
    const s = synth();
    if (!s || !text.trim() || (getTtsMuted() && !force)) return;
    s.cancel();
    const u = new SpeechSynthesisUtterance(text);
    try {
      if (voice.current) u.voice = voice.current;
    } catch {
      /* some engines reject a voice object; the default voice + lang is fine */
    }
    u.lang = voice.current?.lang ?? "en-US";
    u.rate = 1;
    u.pitch = 1;
    const done = () => {
      if (current.current === u) {
        current.current = null;
        setSpeaking(false);
      }
    };
    u.onstart = () => {
      if (current.current === u) setSpeaking(true);
    };
    u.onend = done;
    u.onerror = done; // e.g. "not-allowed" before any user gesture: captions still show
    current.current = u;
    s.speak(u);
  }, []);

  const setMuted = useCallback(
    (m: boolean) => {
      writeMuted(m);
      if (m) cancel();
    },
    [cancel],
  );

  return { supported, speaking, muted, setMuted, speak, cancel };
}
