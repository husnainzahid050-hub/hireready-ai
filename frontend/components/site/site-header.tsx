import Link from "next/link";

import { SITE_NAME } from "@/components/site/config";
import { ButtonLink } from "@/components/ui/button";
import { cn, focusRing } from "@/components/ui/cn";
import { LogoMark } from "@/components/ui/icons";

const NAV = [
  { href: "/#how-it-works", label: "How it works", hideOnMobile: true },
  { href: "/engineering", label: "Engineering", hideOnMobile: false },
  { href: "/privacy", label: "Privacy", hideOnMobile: true },
];

export function Logo({ className }: { className?: string }) {
  return (
    <Link
      href="/"
      className={cn(
        "inline-flex items-center gap-2.5 rounded-lg font-semibold tracking-tight",
        focusRing,
        className,
      )}
    >
      <LogoMark className="size-8" />
      <span className="whitespace-nowrap">{SITE_NAME}</span>
    </Link>
  );
}

/** Shared header. Server component: no client JS. */
export function SiteHeader() {
  return (
    <header className="border-border bg-bg/80 border-b">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between gap-4 px-5 sm:px-6">
        <Logo />
        <nav aria-label="Main" className="flex items-center gap-1 sm:gap-2">
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              className={cn(
                "text-fg-muted hover:bg-surface-sunken hover:text-fg rounded-lg px-2.5 py-2 text-sm font-medium transition-colors",
                n.hideOnMobile && "hidden md:inline-flex",
                focusRing,
              )}
            >
              {n.label}
            </Link>
          ))}
          <ButtonLink href="/start" size="sm" className="ml-1">
            Get started
          </ButtonLink>
        </nav>
      </div>
    </header>
  );
}
