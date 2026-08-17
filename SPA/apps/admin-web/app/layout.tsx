import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "SPA 49 Admin",
  description: "SPA 49 branch operations"
};

export const viewport: Viewport = {
  themeColor: "#4e6148",
  width: "device-width",
  initialScale: 1
};

// The Admin shell depends on Firebase auth and must not be cached as a
// long-lived static document by the Next.js/Cloud Run edge.
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="th">
      <body>{children}</body>
    </html>
  );
}
