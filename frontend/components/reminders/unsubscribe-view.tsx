"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { unsubscribe, unsubscribeStatus } from "@/lib/api";

/** One button, no login, no "are you sure?". Opening the page alone changes nothing. */
export function UnsubscribeView() {
  const { token } = useParams<{ token: string }>();
  const [state, setState] = useState<"loading" | "subscribed" | "done" | "error">("loading");

  useEffect(() => {
    let alive = true;
    unsubscribeStatus(token)
      .then((r) => alive && setState(r.subscribed ? "subscribed" : "done"))
      .catch(() => alive && setState("subscribed")); // still offer the button
    return () => {
      alive = false;
    };
  }, [token]);

  async function stop() {
    try {
      await unsubscribe(token);
      setState("done");
    } catch {
      setState("error");
    }
  }

  return (
    <Card className="space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight">
        {state === "done" ? "You're unsubscribed" : "Stop your prep emails?"}
      </h1>
      {state === "loading" && <p className="text-fg-muted">Loading…</p>}
      {(state === "subscribed" || state === "error") && (
        <>
          <p className="text-fg-muted">
            You won&apos;t get any more HireReady prep emails, and your email address and plan are
            deleted right away.
          </p>
          <Button onClick={stop}>Unsubscribe</Button>
          {state === "error" && (
            <p role="alert" className="text-danger-fg">
              That didn&apos;t work. Please try again.
            </p>
          )}
        </>
      )}
      {state === "done" && (
        <p role="status" className="text-fg-muted">
          No more emails will be sent, and we&apos;ve deleted your email address and plan.{" "}
          <Link href="/" className="text-link underline underline-offset-2">
            Back to HireReady
          </Link>
        </p>
      )}
    </Card>
  );
}
