import type { NextConfig } from "next";

const TRUTHY = ["true", "1", "yes", "on"];

/**
 * Static demo mode (recorded runs played in the browser, no API). An explicit
 * NEXT_PUBLIC_DEMO_MODE wins; otherwise it is on for Vercel builds that have no API to talk to.
 */
function demoModeFlag(): "true" | "false" {
  const explicit = process.env.NEXT_PUBLIC_DEMO_MODE?.trim().toLowerCase();
  if (explicit) return TRUTHY.includes(explicit) ? "true" : "false";
  return process.env.VERCEL && !process.env.NEXT_PUBLIC_API_BASE ? "true" : "false";
}

/** A public live deployment (shows the "Live demo" banner). Off unless explicitly turned on. */
function publicDemoFlag(): "true" | "false" {
  const explicit = process.env.NEXT_PUBLIC_PUBLIC_DEMO?.trim().toLowerCase() ?? "";
  return TRUTHY.includes(explicit) ? "true" : "false";
}

const nextConfig: NextConfig = {
  env: {
    NEXT_PUBLIC_DEMO_MODE: demoModeFlag(),
    NEXT_PUBLIC_PUBLIC_DEMO: publicDemoFlag(),
  },
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
