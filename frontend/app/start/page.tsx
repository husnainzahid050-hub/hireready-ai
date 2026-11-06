import type { Metadata } from "next";
import Link from "next/link";

import { DemoButton } from "@/components/demo-button";
import { StartForm } from "@/components/start-form";

export const metadata: Metadata = { title: "Start · HireReady AI" };

export default function StartPage() {
  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-12">
      <Link href="/" className="text-sm text-zinc-500 hover:underline">
        ← HireReady AI
      </Link>
      <h1 className="mt-4 text-3xl font-semibold tracking-tight">Set up your mock interview</h1>
      <p className="mt-2 text-zinc-600 dark:text-zinc-400">
        Upload your CV and paste the job you&apos;re applying for. We&apos;ll show your skill gaps
        with evidence, likely questions, and a 7-day plan.
      </p>
      <div className="mt-6 flex items-center gap-3 rounded-xl bg-zinc-100 p-4 text-sm dark:bg-zinc-900">
        <span className="flex-1">Just exploring? Try it with a fictional sample CV.</span>
        <DemoButton className="py-2 text-sm" />
      </div>
      <div className="mt-10">
        <StartForm />
      </div>
    </main>
  );
}
