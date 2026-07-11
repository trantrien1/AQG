import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  // Pin the Turbopack workspace root to this folder so it resolves the local
  // `next` package correctly (avoids the "Next.js package not found" panic /
  // HMR reload loop caused by stray parent/pnpm workspace signals).
  turbopack: {
    root: path.resolve(__dirname),
  },
  // Docker production: `next build` xuất .next/standalone (server.js tự chạy,
  // không cần node_modules đầy đủ trong image).
  output: "standalone",
};

export default nextConfig;
