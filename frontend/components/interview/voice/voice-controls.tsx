"use client";

import { buttonClasses } from "@/components/ui/button";
import { cn } from "@/components/ui/cn";
import { Replay, Volume, VolumeOff } from "@/components/ui/icons";

/** Interviewer voice controls: replay the current question and mute (persisted). */
export function VoiceControls({
  muted,
  onToggleMute,
  onReplay,
  speaking,
}: {
  muted: boolean;
  onToggleMute: () => void;
  onReplay: () => void;
  speaking: boolean;
}) {
  const btn = buttonClasses({ variant: "secondary", size: "md", className: "px-3" });
  return (
    <div className="flex items-center gap-2">
      <button type="button" onClick={onReplay} className={btn} disabled={speaking}>
        <Replay className="size-4" />
        Replay
        <span className="sr-only"> the question out loud</span>
      </button>
      <button
        type="button"
        onClick={onToggleMute}
        aria-pressed={muted}
        className={cn(
          btn,
          "aria-pressed:border-accent aria-pressed:bg-accent-soft aria-pressed:text-accent-soft-fg",
        )}
        title={muted ? "Questions are not read aloud" : "Questions are read aloud"}
      >
        {muted ? <VolumeOff className="size-4" /> : <Volume className="size-4" />}
        Mute voice
      </button>
    </div>
  );
}
