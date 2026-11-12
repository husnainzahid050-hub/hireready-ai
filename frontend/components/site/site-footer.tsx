import Link from "next/link";

import { GITHUB_URL, LINKEDIN_URL, TAGLINE } from "@/components/site/config";
import { Logo } from "@/components/site/site-header";
import { cn, focusRing } from "@/components/ui/cn";
import { Github, Linkedin } from "@/components/ui/icons";

const linkCls = cn("rounded text-fg-muted transition-colors hover:text-fg", focusRing);

export function SiteFooter() {
  return (
    <footer className="border-border bg-surface-muted mt-auto border-t print:hidden">
      <div className="mx-auto grid w-full max-w-6xl gap-10 px-5 py-12 sm:px-6 md:grid-cols-[1.5fr_1fr_1fr]">
        <div className="space-y-3">
          <Logo />
          <p className="text-fg-muted max-w-xs text-sm">{TAGLINE}</p>
          <p className="text-fg-subtle max-w-xs text-sm">
            Audio is never stored. Guest data expires after 7 days.
          </p>
        </div>

        <nav aria-label="Product" className="space-y-3 text-sm">
          <p className="text-fg font-semibold">Product</p>
          <ul className="space-y-2">
            <li>
              <Link href="/start" className={linkCls}>
                Start a mock interview
              </Link>
            </li>
            <li>
              <Link href="/#how-it-works" className={linkCls}>
                How it works
              </Link>
            </li>
            <li>
              <Link href="/#faq" className={linkCls}>
                FAQ
              </Link>
            </li>
          </ul>
        </nav>

        <nav aria-label="Project" className="space-y-3 text-sm">
          <p className="text-fg font-semibold">Project</p>
          <ul className="space-y-2">
            <li>
              <Link href="/engineering" className={linkCls}>
                Engineering
              </Link>
            </li>
            <li>
              <Link href="/privacy" className={linkCls}>
                Privacy
              </Link>
            </li>
            <li>
              <a href={GITHUB_URL} className={cn(linkCls, "inline-flex items-center gap-1.5")}>
                <Github className="size-4" /> GitHub
              </a>
            </li>
            {LINKEDIN_URL && (
              <li>
                <a href={LINKEDIN_URL} className={cn(linkCls, "inline-flex items-center gap-1.5")}>
                  <Linkedin className="size-4" /> LinkedIn
                </a>
              </li>
            )}
          </ul>
        </nav>
      </div>
      <div className="border-border border-t">
        <p className="text-fg-subtle mx-auto w-full max-w-6xl px-5 py-5 text-xs sm:px-6">
          A portfolio project. Example data on this site is fictional.
        </p>
      </div>
    </footer>
  );
}
