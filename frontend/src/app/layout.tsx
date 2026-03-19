import type { Metadata } from "next";
import { Inter } from "next/font/google";

import { AuthProvider } from "@/components/providers/auth-provider";
import { BranchProvider } from "@/components/providers/branch-provider";

import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter"
});

export const metadata: Metadata = {
  title: "The 49 - Smart P&L",
  description: "Frontend for The 49 Smart P&L Analysis"
};

export default function RootLayout({
  children
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${inter.variable} font-sans antialiased`}>
        <AuthProvider>
          <BranchProvider>{children}</BranchProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
