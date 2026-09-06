"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, BookOpen, FileText, House, Inbox, ScrollText, Settings } from "lucide-react";

import { cn } from "@/lib/utils";
import { ThemeToggle } from "./theme-toggle";

const LINKS = [
  { href: "/", label: "Home", icon: House, exact: true },
  { href: "/how-it-works", label: "How it works", icon: BookOpen, exact: false },
  { href: "/docs", label: "Docs·手册", icon: FileText, exact: false },
  { href: "/inbox", label: "Inbox", icon: Inbox, exact: false },
  { href: "/audit", label: "Audit", icon: ScrollText, exact: false },
  { href: "/report", label: "Report", icon: BarChart3, exact: false },
  { href: "/settings", label: "Settings", icon: Settings, exact: false },
] as const;

/** Top navigation. Client component so it can highlight the active route. */
export function Nav() {
  const pathname = usePathname();
  return (
    <header className="sticky top-0 z-20 border-b border-zinc-200 bg-white/80 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/80">
      <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-3">
        <Link
          href="/"
          className="flex items-center gap-2 font-semibold text-zinc-900 dark:text-zinc-100"
        >
          {/* Vector mark: crisp at nav size (the raster illustration blurs when small). */}
          <img
            src="/everlink-mark.svg"
            alt="EverLink logo"
            width={28}
            height={28}
            className="h-7 w-7 rounded-md"
          />
          <span>EverLink</span>
        </Link>
        <nav className="ml-auto flex items-center gap-1">
          {LINKS.map(({ href, label, icon: Icon, exact }) => {
            const active = exact ? pathname === href : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  active
                    ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                    : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100",
                )}
              >
                <Icon className="h-4 w-4" />
                <span className="hidden sm:inline">{label}</span>
              </Link>
            );
          })}
          <ThemeToggle />
        </nav>
      </div>
    </header>
  );
}
