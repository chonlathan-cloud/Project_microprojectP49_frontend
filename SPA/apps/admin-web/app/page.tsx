"use client";

import { AdminDashboard } from "@/components/admin-dashboard";
import { AdminAuth } from "@/components/admin-auth";

export default function HomePage() {
  return <AdminAuth>{(user) => <AdminDashboard user={user} />}</AdminAuth>;
}
