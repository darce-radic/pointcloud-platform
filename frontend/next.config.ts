import type { NextConfig } from "next";
import path from "path";
import CopyWebpackPlugin from "copy-webpack-plugin";

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
  // Cesium requires its static assets to be available at a known base URL
  env: {
    NEXT_PUBLIC_CESIUM_BASE_URL: '/cesium',
  },
  webpack: (config, { isServer }) => {
    if (!isServer) {
      // Copy Cesium static assets to public/cesium at build time
      const cesiumSource = path.join(
        path.dirname(require.resolve('cesium/package.json')),
        'Build',
        'Cesium'
      );
      config.plugins.push(
        new CopyWebpackPlugin({
          patterns: [
            {
              from: path.join(cesiumSource, 'Workers'),
              to: path.join(__dirname, 'public', 'cesium', 'Workers'),
            },
            {
              from: path.join(cesiumSource, 'Assets'),
              to: path.join(__dirname, 'public', 'cesium', 'Assets'),
            },
            {
              from: path.join(cesiumSource, 'ThirdParty'),
              to: path.join(__dirname, 'public', 'cesium', 'ThirdParty'),
            },
            {
              from: path.join(cesiumSource, 'Widgets'),
              to: path.join(__dirname, 'public', 'cesium', 'Widgets'),
            },
          ],
        })
      );
    }
    return config;
  },
};

export default nextConfig;
