import type { Metadata, Viewport } from "next";
import { Noto_Sans_Thai, Noto_Serif_Thai } from "next/font/google";
import type { ReactNode } from "react";

import "./globals.css";

const bodyFont = Noto_Sans_Thai({
  subsets: ["latin", "thai"],
  variable: "--font-body",
  display: "swap"
});

const displayFont = Noto_Serif_Thai({
  subsets: ["latin", "thai"],
  variable: "--font-display",
  display: "swap"
});

export const metadata: Metadata = {
  title: "SPA 49 Booking",
  description: "Book a SPA 49 treatment"
};

export const viewport: Viewport = {
  themeColor: "#4e6148",
  width: "device-width",
  initialScale: 1
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="th" className={`${bodyFont.variable} ${displayFont.variable}`}>
      <body>{children}</body>
    </html>
  );
}
