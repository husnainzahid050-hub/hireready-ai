import { HealthStatus } from "@/components/health-status";

// Phase 0 placeholder. The real landing page is built in Phase 6.
export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-6 px-6">
      <h1 className="text-3xl font-semibold tracking-tight">HireReady AI</h1>
      <p className="text-lg text-zinc-600 dark:text-zinc-400">
        Paste the job. Upload your CV. Walk into the interview ready.
      </p>
      <HealthStatus />
    </main>
  );
}
