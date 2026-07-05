"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { useRouter } from "next/navigation";
import { LogOut, Menu, UserCircle2 } from "lucide-react";
import { signOut } from "firebase/auth";

import { useAuth } from "@/components/providers/auth-provider";
import { Sidebar } from "@/components/layout/sidebar";
import { Button } from "@/components/ui/button";
import { auth } from "@/lib/firebase";

export default function DashboardLayout({
  children
}: {
  children: ReactNode;
}) {
  const router = useRouter();
  const { user, loading, displayName } = useAuth();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  useEffect(() => {
    if (!loading && !user) {
      router.replace("/login");
    }
  }, [loading, router, user]);

  useEffect(() => {
    const savedState = window.localStorage.getItem("the49-sidebar-collapsed");

    if (savedState !== null) {
      setSidebarCollapsed(savedState === "true");
    }
  }, []);

  async function handleLogout() {
    await signOut(auth);
    router.replace("/login");
  }

  function handleSidebarToggle() {
    setSidebarCollapsed((current) => {
      const next = !current;
      window.localStorage.setItem("the49-sidebar-collapsed", String(next));

      return next;
    });
  }

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-100">
        <p className="text-sm text-slate-600">Checking authentication...</p>
      </main>
    );
  }

  if (!user) {
    return null;
  }

  return (
    <div className="flex min-h-screen bg-slate-100">
      <div className="hidden md:block">
        <Sidebar
          collapsed={sidebarCollapsed}
          onToggleCollapsed={handleSidebarToggle}
        />
      </div>

      {mobileSidebarOpen ? (
        <div className="fixed inset-0 z-40 md:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            className="absolute inset-0 bg-slate-900/45"
            onClick={() => setMobileSidebarOpen(false)}
          />
          <div className="relative h-full w-72 max-w-[85vw] shadow-xl">
            <Sidebar
              variant="mobile"
              onClose={() => setMobileSidebarOpen(false)}
              onNavigate={() => setMobileSidebarOpen(false)}
            />
          </div>
        </div>
      ) : null}

      <section className="flex min-h-screen flex-1 flex-col">
        <header className="flex h-16 items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-2">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="Open navigation"
              title="Open navigation"
              className="md:hidden"
              onClick={() => setMobileSidebarOpen(true)}
            >
              <Menu className="h-4 w-4" />
            </Button>
            <h1 className="truncate text-lg font-semibold text-slate-900">Dashboard</h1>
          </div>

          <div className="flex min-w-0 items-center gap-2 sm:gap-3">
            <div className="hidden items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 sm:flex">
              <UserCircle2 className="h-4 w-4 text-slate-600" />
              <span className="max-w-44 truncate text-sm text-slate-700">
                {displayName}
              </span>
            </div>
            <Button type="button" variant="outline" size="sm" onClick={handleLogout}>
              <LogOut className="mr-2 h-4 w-4" />
              Logout
            </Button>
          </div>
        </header>

        <main className="flex-1 p-6">{children}</main>
      </section>
    </div>
  );
}
