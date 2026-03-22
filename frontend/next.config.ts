import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output for Railway/Docker deployment
  output: "standalone",
  images: {
    remotePatterns: [
      { protocol: 'https', hostname: '*.supabase.co' },
      { protocol: 'https', hostname: '*.amazonaws.com' },
      { protocol: 'https', hostname: '*.cloudfront.net' },
    ],
  },
};

export default nextConfig;
