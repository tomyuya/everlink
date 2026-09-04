import type { Metadata } from "next";
import type { ReactNode } from "react";
import { ThemeProvider } from "next-themes";

import { Nav } from "@/components/nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "EverLink · Decision Board",
  description:
    "EverLink's minimal human-in-the-loop inbox: approve or reject the link-rot fixes that actually need a human.",
  icons: { icon: "/everlink-logo.png", apple: "/everlink-logo.png" },
  openGraph: { images: ["/everlink-logo.png"] },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen bg-zinc-50 text-zinc-900 antialiased dark:bg-zinc-950 dark:text-zinc-100">
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
          <Nav />
          <main className="mx-auto w-full max-w-6xl px-4 py-8">{children}</main>
          <footer className="mx-auto w-full max-w-6xl px-4 pb-10 text-xs text-zinc-400 dark:text-zinc-600">
            EverLink · autonomous link-rot steward · the only screen you open is this one.
          </footer>
        </ThemeProvider>
      </body>
    </html>
  );
}
