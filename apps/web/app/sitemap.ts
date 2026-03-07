import type { MetadataRoute } from "next";

export default function sitemap(): MetadataRoute.Sitemap {
  const site = process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";
  return [
    { url: `${site}/`, changeFrequency: "daily", priority: 1.0 },
    { url: `${site}/app`, changeFrequency: "daily", priority: 0.95 },
    { url: `${site}/sample-report`, changeFrequency: "weekly", priority: 0.65 },
    { url: `${site}/faq`, changeFrequency: "monthly", priority: 0.5 },
    { url: `${site}/imprint`, changeFrequency: "monthly", priority: 0.4 },
    { url: `${site}/privacy`, changeFrequency: "monthly", priority: 0.4 },
  ];
}
