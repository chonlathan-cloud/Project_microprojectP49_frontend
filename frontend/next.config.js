/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  webpack: (config, { dev, isServer }) => {
    // Workaround for intermittent missing vendor chunk files in dev mode.
    // Disable webpack filesystem cache only for server-side dev builds.
    if (dev && isServer) {
      config.cache = false;
    }
    return config;
  }
};

module.exports = nextConfig;
