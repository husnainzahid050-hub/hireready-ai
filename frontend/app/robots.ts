import type { MetadataRoute } from "next";

import { SITE_URL } from "@/components/site/config";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      // Private, per-user pages (also marked noindex) and the API proxy. /r/ (shared reports)
      // is deliberately NOT disallowed: a crawler that may not fetch the page never sees its
      // noindex, so a link pasted elsewhere could still be indexed as a bare URL. /r/* sends
      // X-Robots-Tag: noindex instead (next.config.ts).
      disallow: ["/session/", "/api/"],
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
