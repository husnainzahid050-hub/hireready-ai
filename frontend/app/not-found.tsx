import type { Metadata } from "next";

import { ButtonLink } from "@/components/ui/button";
import { Container } from "@/components/ui/section";

export const metadata: Metadata = { title: "Page not found" };

export default function NotFound() {
  return (
    <main className="flex flex-1 items-center py-20">
      <Container size="prose" className="space-y-6 text-center">
        <p className="text-sm font-semibold tracking-wide text-link uppercase">404</p>
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          We couldn&apos;t find that page
        </h1>
        <p className="text-fg-muted">
          The link may be mistyped, or it pointed to a session that has expired. Sessions are
          private to the browser that created them and expire after 7 days.
        </p>
        <div className="flex flex-col justify-center gap-3 sm:flex-row">
          <ButtonLink href="/">Back to home</ButtonLink>
          <ButtonLink href="/start" variant="secondary">
            Start a new mock interview
          </ButtonLink>
        </div>
      </Container>
    </main>
  );
}
