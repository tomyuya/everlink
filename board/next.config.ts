import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next 16 dropped the `eslint` config key (it no longer runs ESLint during build).
  // The build gate for this board is type + compile correctness: `tsc --noEmit` and
  // `next build` (which type-checks by default). Lint style is a dev concern.

  /**
   * /how-it-works was merged into "/": the two pages rendered three whole
   * components verbatim in common (OnboardingPaths, Pipeline, AutomationPanel)
   * and each opened with the same "what EverLink is" pitch, so the sections that
   * were genuinely unique to it moved to the landing page instead.
   *
   * The route stays alive as a PERMANENT redirect because README.md, both shipped
   * manuals (board/content/manual.*.md) and the hackathon submission material all
   * link to it by URL — deleting it outright would turn those into 404s.
   */
  async redirects() {
    return [{ source: "/how-it-works", destination: "/", permanent: true }];
  },
};

export default nextConfig;
