import type { MetadataRoute } from "next";

import { SITE_URL } from "@/components/site/config";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      // Private, per-user pages (also marked noindex) and the API proxy.
      disallow: ["/session/", "/r/", "/api/"],
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
