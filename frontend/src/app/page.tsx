"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { BarChart3, FileUp, Sparkles, WalletCards } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useAuth } from "@/components/providers/auth-provider";

export default function HomePage() {
  const router = useRouter();
  const { user, loading } = useAuth();

  useEffect(() => {
    if (loading) {
      return;
    }
    if (user) {
      router.replace("/dashboard");
    }
  }, [loading, router, user]);

  if (loading || user) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-100 p-6">
        <p className="text-sm text-slate-600">Checking authentication...</p>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-100 p-6">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-8 py-10">
        <section className="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm sm:p-10">
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            The 49 Smart P&L
          </p>
          <h1 className="mt-3 text-3xl font-semibold text-slate-900 sm:text-4xl">
            Expense Intelligence for Multi-Store Operations
          </h1>
          <p className="mt-4 max-w-2xl text-slate-600">
            Upload receipts, import POS sales, and get real-time P&amp;L visibility with AI-assisted
            insights for managers and executives.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Link
              href="/login"
              className="inline-flex h-10 items-center justify-center rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-800"
            >
              Sign in
            </Link>
            <Link
              href="/signup"
              className="inline-flex h-10 items-center justify-center rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-900 transition-colors hover:bg-slate-100"
            >
              Create account
            </Link>
          </div>
        </section>

        <section className="grid gap-4 md:grid-cols-3">
          <Card>
            <CardContent className="space-y-2 p-5">
              <FileUp className="h-5 w-5 text-slate-700" />
              <h2 className="text-base font-semibold text-slate-900">1. Upload Receipt</h2>
              <p className="text-sm text-slate-600">
                Upload receipt images and let OCR + AI extract expense items in draft mode.
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="space-y-2 p-5">
              <WalletCards className="h-5 w-5 text-slate-700" />
              <h2 className="text-base font-semibold text-slate-900">2. Import POS Revenue</h2>
              <p className="text-sm text-slate-600">
                Import CSV/Excel POS files to bring daily revenue into analytics automatically.
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="space-y-2 p-5">
              <BarChart3 className="h-5 w-5 text-slate-700" />
              <h2 className="text-base font-semibold text-slate-900">3. Analyze & Act</h2>
              <p className="text-sm text-slate-600">
                Review dashboard KPIs and ask AI Insight for branch-level recommendations.
              </p>
            </CardContent>
          </Card>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-5 sm:p-6">
          <div className="flex items-start gap-3">
            <Sparkles className="mt-1 h-5 w-5 text-slate-700" />
            <div>
              <h3 className="text-base font-semibold text-slate-900">Who is this for?</h3>
              <p className="mt-1 text-sm text-slate-600">
                Staff upload and verify transactions. Managers and Executives monitor performance by
                branch, category, and date range.
              </p>
            </div>
          </div>
          <div className="mt-4">
            <Button type="button" onClick={() => router.push("/login")}>
              Start with Sign in
            </Button>
          </div>
        </section>
      </div>
    </main>
  );
}
