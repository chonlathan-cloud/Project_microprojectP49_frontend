"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

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
      return;
    }
    router.replace("/login");
  }, [loading, router, user]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-100 p-6">
      <p className="text-sm text-slate-600">Checking authentication...</p>
    </main>
  );
}
