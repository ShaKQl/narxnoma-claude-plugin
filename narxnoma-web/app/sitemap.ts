import type { MetadataRoute } from "next";
import { getBrandsByCategory } from "@/lib/queries";

export const revalidate = 3600;

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const base = "https://narxnoma.uz";
  const brands = await getBrandsByCategory();
  const urls: MetadataRoute.Sitemap = [
    { url: base, changeFrequency: "daily", priority: 1 },
    { url: `${base}/search`, changeFrequency: "daily", priority: 0.9 },
    { url: `${base}/stores`, changeFrequency: "daily", priority: 0.4 },
    { url: `${base}/about`, changeFrequency: "monthly", priority: 0.3 },
    { url: `${base}/c/smartphones`, changeFrequency: "daily", priority: 0.8 },
  ];
  for (const b of brands) {
    urls.push({
      url: `${base}/c/${b.category}/${b.brand}`,
      changeFrequency: "daily",
      priority: 0.7,
    });
  }
  return urls;
}