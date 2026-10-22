import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";

import { DEMO_MODE } from "@/lib/api";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Agent Failure Autopsy",
  description:
    "TinyFish agents can do the work. We tell you when they didn't, why, and fix it automatically.",
};

const NAV = [
  { href: "/", label: "Run" },
  { href: "/results", label: "Results" },
  { href: "/dev", label: "Dev" },
];

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        {DEMO_MODE && (
          <div className="border-b border-amber-500/30 bg-amber-950/50 px-6 py-1.5 text-center text-sm text-amber-100">
            Demo deployment · replays bundled runs · live runs need the API
          </div>
        )}
        <header className="border-b border-slate-800 bg-slate-950/80">
          <div className="mx-auto flex w-full max-w-[1600px] flex-wrap items-center justify-between gap-x-6 gap-y-2 px-6 py-4">
            <div>
              <Link href="/" className="text-lg font-semibold tracking-tight text-slate-50">
                Agent Failure Autopsy
              </Link>
              <p className="text-sm text-slate-400">
                TinyFish agents can do the work. We tell you when they didn&apos;t, why, and fix it.
              </p>
            </div>
            <nav className="flex gap-1">
              {NAV.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="rounded-md px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800 hover:text-slate-50"
                >
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>
        </header>
        <div className="mx-auto w-full min-w-0 max-w-[1600px] flex-1 px-6 py-6">{children}</div>
      </body>
    </html>
  );
}
