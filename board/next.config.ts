import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next 16 dropped the `eslint` config key (it no longer runs ESLint during build).
  // The build gate for this board is type + compile correctness: `tsc --noEmit` and
  // `next build` (which type-checks by default). Lint style is a dev concern.
};

export default nextConfig;
