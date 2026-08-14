import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  transpilePackages: ["@spa/shared-types"],
  poweredByHeader: false
};

export default nextConfig;
