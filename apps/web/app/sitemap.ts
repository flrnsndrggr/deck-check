import type { MetadataRoute } from "next";

export default function sitemap(): MetadataRoute.Sitemap {
  const site = process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";
  return [
    { url: `${site}/`, changeFrequency: "daily", priority: 1.0 },
    { url: `${site}/imprint`, changeFrequency: "monthly", priority: 0.4 },
    { url: `${site}/privacy`, changeFrequency: "monthly", priority: 0.4 },
  ];
}
