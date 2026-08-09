import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Pin the project root explicitly: a stray D:\ASUS\package-lock.json makes
  // Next infer the wrong workspace root and bake broken absolute paths into
  // the server bundle.
  outputFileTracingRoot: path.join(__dirname),
  // Pages are computed from live data; ISR refreshes them after crawler cycles.
  experimental: {
    staleTimes: { dynamic: 0 },
  },
};

export default nextConfig;