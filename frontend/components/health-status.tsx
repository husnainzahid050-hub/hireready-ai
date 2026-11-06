"use client";

import { useEffect, useState } from "react";

type Health = {
  status: "ok";
  version: string;
  environment: string;
  dependencies: Record<string, string>;
};

type State =
  { kind: "loading" } | { kind: "ok"; data: Health } | { kind: "error"; message: string };

export function HealthStatus() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/v1/health", { signal: controller.signal, cache: "no-store" })
      .then(async (r) => {
        if (!r.ok) throw new Error(`Backend returned ${r.status}`);
        setState({ kind: "ok", data: (await r.json()) as Health });
      })
      .catch((e: unknown) => {
        if (controller.signal.aborted) return;
        setState({ kind: "error", message: e instanceof Error ? e.message : "Unknown error" });
      });
    return () => controller.abort();
  }, []);

  if (state.kind === "loading") {
    return (
      <p className="text-zinc-500" role="status">
        Checking backend…
      </p>
    );
  }
  if (state.kind === "error") {
    return (
      <p className="text-red-600 dark:text-red-400" role="alert">
        Backend unreachable: {state.message}
      </p>
    );
  }
  return (
    <div role="status" className="space-y-2">
      <p className="font-medium text-emerald-700 dark:text-emerald-400">
        Backend OK · v{state.data.version} · {state.data.environment}
      </p>
      <ul className="text-sm text-zinc-600 dark:text-zinc-400">
        {Object.entries(state.data.dependencies).map(([name, status]) => (
          <li key={name}>
            {name}: {status}
          </li>
        ))}
      </ul>
    </div>
  );
}
