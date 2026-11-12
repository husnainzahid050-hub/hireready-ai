"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ApiError, getReminder, reminderAction, type ReminderStatus } from "@/lib/api";

/**
 * Landing page for links in reminder emails. Opening it changes nothing (mail scanners prefetch
 * links); every action is a button press (POST). `?day=N` comes from "Mark today done".
 */
export function ReminderView() {
  const { token } = useParams<{ token: string }>();
  const day = Number(useSearchParams().get("day")) || null;
  const [data, setData] = useState<ReminderStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getReminder(token)
      .then((d) => alive && setData(d))
      .catch((e: unknown) => {
        if (alive)
          setError(e instanceof ApiError ? e.message : "We couldn't load this link. Try again.");
      });
    return () => {
      alive = false;
    };
  }, [token]);

  async function act(action: "confirm" | "done" | "resume", message: string) {
    setBusy(true);
    setError(null);
    try {
      setData(await reminderAction(token, action, day ?? undefined));
      setNote(message);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  if (error && !data) {
    return (
      <Card className="space-y-3">
        <p role="alert">{error}</p>
        <Link href="/start" className="text-link font-medium underline underline-offset-2">
          Start a new practice session
        </Link>
      </Card>
    );
  }
  if (!data) return <p className="text-fg-muted">Loading…</p>;

  const dots = Array.from({ length: data.days_total }, (_, i) => (i < data.day ? "●" : "○"));
  const canMarkDone =
    day !== null &&
    day <= data.day &&
    day > data.last_done_day &&
    (data.status === "active" || data.status === "finished");

  return (
    <Card className="space-y-5">
      <div className="space-y-1">
        <p className="text-fg-muted text-sm">7-day prep plan · {data.role_title || "your role"}</p>
        <h1 className="text-2xl font-semibold tracking-tight">
          {data.status === "pending" && "Start your 7-day plan?"}
          {data.status === "active" && `Day ${data.day} of ${data.days_total}`}
          {data.status === "paused" && "Your prep emails are paused"}
          {data.status === "finished" && "Plan finished"}
        </h1>
        <p aria-label={`${data.day} of ${data.days_total} days sent`} className="tracking-widest">
          {dots.join(" ")}
        </p>
      </div>

      {data.status === "pending" && (
        <div className="space-y-3">
          <p className="text-fg-muted">
            One short email a day with one task, for 7 days, then they stop. Day 1 arrives right
            after you confirm.
          </p>
          <Button
            onClick={() => act("confirm", "Confirmed. Day 1 is on its way.")}
            disabled={busy}
          >
            Start my 7-day plan
          </Button>
        </div>
      )}
      {canMarkDone && (
        <Button onClick={() => act("done", "Nice work. See you tomorrow.")} disabled={busy}>
          Mark day {day} done
        </Button>
      )}
      {data.status === "paused" && (
        <div className="space-y-3">
          <p className="text-fg-muted">
            Nothing more will be sent unless you restart. The next day arrives tomorrow morning.
          </p>
          <Button onClick={() => act("resume", "Restarted. Next email tomorrow.")} disabled={busy}>
            Restart my plan
          </Button>
        </div>
      )}
      {data.status === "finished" && (
        <p className="text-fg-muted">
          Take a fresh mock interview to see how far you&apos;ve moved.{" "}
          <Link href="/start" className="text-link font-medium underline underline-offset-2">
            Practise again
          </Link>
        </p>
      )}

      <ol className="text-fg-muted space-y-1 text-sm">
        {data.plan.map((d) => (
          <li key={d.day}>
            Day {d.day}: {d.focus}
          </li>
        ))}
      </ol>

      {note && (
        <p role="status" className="text-success-fg font-medium">
          {note}
        </p>
      )}
      {error && (
        <p role="alert" className="text-danger-fg">
          {error}
        </p>
      )}
      <p className="text-fg-muted text-sm">
        <Link href={`/unsubscribe/${token}`} className="underline underline-offset-2">
          Unsubscribe
        </Link>{" "}
        · we never use this link to open your report or session.
      </p>
    </Card>
  );
}
