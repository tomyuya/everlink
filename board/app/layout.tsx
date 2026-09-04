import type { Metadata } from "next";
import type { ReactNode } from "react";
import { ThemeProvider } from "next-themes";

import { Nav } from "@/components/nav";
import "./globals.css";

/** Absolute origin for resolving OG/social images (Vercel preview-aware). */
const siteOrigin =
  process.env.NEXT_PUBLIC_SITE_URL ||
  (process.env.VERCEL_URL ? `https://${process.env.VERCEL_URL}` : "https://everlink-seven.vercel.app");

export const metadata: Metadata = {
  metadataBase: new URL(siteOrigin),
  title: "EverLink · Decision Board",
  description:
    "EverLink autonomously detects and repairs link rot on first-party sites. This board is the human-in-the-loop surface: it only asks you to approve or reject the fixes risky enough to need a person.",
  icons: {
    icon: [{ url: "/everlink-mark.svg", type: "image/svg+xml" }],
    apple: "/everlink-logo.png",
  },
  openGraph: {
    title: "EverLink · the autonomous link-rot steward",
    description:
      "Scans outbound links, detects rot, repairs it itself — and only stops for a human when a fix is risky. Built on AWS Strands SDK + Bedrock.",
    images: ["/everlink-logo.png"],
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen bg-zinc-50 text-zinc-900 antialiased dark:bg-zinc-950 dark:text-zinc-100">
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
          <Nav />
          <main className="mx-auto w-full max-w-6xl px-4 py-8">{children}</main>
          <footer className="mx-auto w-full max-w-6xl px-4 pb-10 text-xs text-zinc-400 dark:text-zinc-600">
            EverLink · autonomous link-rot steward on AWS Strands + Bedrock · humans approve
            only the risky fixes.
          </footer>
        </ThemeProvider>
      </body>
    </html>
  );
}
