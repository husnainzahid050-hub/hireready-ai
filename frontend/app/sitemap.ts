import type { MetadataRoute } from "next";

import { SITE_URL } from "@/components/site/config";

// Public pages only. /session/* and /r/* (shared reports) are private and never listed.
export default function sitemap(): MetadataRoute.Sitemap {
  return [
    { url: `${SITE_URL}/`, changeFrequency: "weekly", priority: 1 },
    { url: `${SITE_URL}/start`, changeFrequency: "monthly", priority: 0.8 },
    { url: `${SITE_URL}/engineering`, changeFrequency: "weekly", priority: 0.7 },
    { url: `${SITE_URL}/privacy`, changeFrequency: "monthly", priority: 0.4 },
  ];
}
