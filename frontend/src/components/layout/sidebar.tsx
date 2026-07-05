"use client";

import type { ComponentType } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ArrowLeftRight,
  BarChart3,
  ChevronLeft,
  ChevronRight,
  FileUp,
  Home,
  Settings,
  X,
  WalletCards
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type NavItem = {
  href: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
};

const navItems: NavItem[] = [
  { href: "/dashboard/welcome", label: "Welcome", icon: Home },
  { href: "/dashboard", label: "Dashboard", icon: BarChart3 },
  { href: "/transactions", label: "Transactions", icon: ArrowLeftRight },
  { href: "/dashboard/upload-receipt", label: "Upload Receipt", icon: FileUp },
  { href: "/dashboard/pos-import", label: "POS Import", icon: WalletCards },
  { href: "/dashboard/settings", label: "Settings", icon: Settings }
];

type SidebarProps = {
  collapsed?: boolean;
  onNavigate?: () => void;
  onClose?: () => void;
  onToggleCollapsed?: () => void;
  variant?: "desktop" | "mobile";
};

export function Sidebar({
  collapsed = false,
  onNavigate,
  onClose,
  onToggleCollapsed,
  variant = "desktop"
}: SidebarProps) {
  const pathname = usePathname();
  const compact = variant === "desktop" && collapsed;

  return (
    <aside
      className={cn(
        "flex h-screen shrink-0 flex-col border-r border-slate-200 bg-white transition-[width] duration-200",
        variant === "mobile" ? "w-72" : compact ? "w-20" : "w-64"
      )}
    >
      <div
        className={cn(
          "flex h-16 items-center border-b border-slate-200",
          compact ? "justify-center px-3" : "justify-between px-5"
        )}
      >
        <div className={cn("min-w-0", compact && "sr-only")}>
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">The 49</p>
          <h2 className="mt-1 truncate text-lg font-semibold text-slate-900">Smart P&L</h2>
        </div>

        {compact ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Expand sidebar"
            title="Expand sidebar"
            onClick={onToggleCollapsed}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        ) : variant === "mobile" ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Close navigation"
            title="Close navigation"
            onClick={onClose}
          >
            <X className="h-4 w-4" />
          </Button>
        ) : (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Collapse sidebar"
            title="Collapse sidebar"
            onClick={onToggleCollapsed}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
        )}
      </div>

      <nav className={cn("flex-1 space-y-1 p-3", compact && "px-2")}>
        {navItems.map((item) => {
          const active =
            pathname === item.href ||
            (item.href !== "/dashboard" && pathname.startsWith(item.href));
          const Icon = item.icon;

          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onNavigate}
              title={compact ? item.label : undefined}
              className={cn(
                "flex h-10 items-center rounded-md text-sm font-medium transition-colors",
                compact ? "justify-center px-0" : "gap-3 px-3",
                active
                  ? "bg-slate-900 text-white"
                  : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span className={cn("truncate", compact && "sr-only")}>{item.label}</span>
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
